"""Opt-in parameter-dependency summaries, not proofs or audit-grade inputs.

Bodies are let bindings — ``a, b := e1, e2`` declarations bind each
name to its matching right-hand side's dependencies, evaluated in
parallel against the pre-state —
plus ``if``/``else`` and bounded ``for`` statements followed by one or more
explicit scalar return expressions; the result unions every syntactic return's
dependencies (unreachable returns included — reachability is not proven). A
``for`` clause may hold one let-binding initializer, a supported condition and
an inc/dec update on a bound scalar. Integer ``range`` loops — ``for
i := range e`` where the operand is an integer — bind a fresh scoped
index variable carrying the operand's dependencies; composite ranges
are unreachable because no supported binding or literal can produce
them. A scalar ``x = expression``
reassignment replaces the binding's dependencies — it never declares a
new variable. Tuple assignments ``x, y = e1, e2`` are parallel: every
right-hand side evaluates against the pre-state before any store lands.
Compound assignments ``x op= e`` read the old value — the result unions
the binding's current dependencies with the right-hand side's. Loop bodies are
joined to a widening fixed point so dependencies propagating across
iterations are captured (joins, not unrolls — trip counts are never
modelled). ``if`` and expression ``switch`` statements accept a
simple-statement ``initializer`` — the same mechanism as a for-clause
init, with the bound name scoped to the statement (a later out-of-scope
reference simply never resolves). ``switch`` without ``fallthrough``
joins the same way: the tag and every case guard are evaluated
(effect-free), each clause body runs in its own scope and its
reassignments union back. ``var`` declarations bind like lets —
``var a, b T`` is the dep-free zero value and ``var a, b = x, y``
binds name-wise like ``:=`` (grouped ``var (...)`` forms are a parser
gap). ``x++``/``x--`` on a
bound scalar are dependency-preserving, on an imported member they
record the member write, and ``_ = expression``
evaluates-and-discards like a condition. Expression statements — only
calls are legal — evaluate for their recorded transfer and discard the
result. An unlabelled
``break``/``continue`` marks its innermost loop or switch construct as
exited — every later statement in that body is a may-assignment whose
writes union instead of replace, because the jump may have skipped them
(labelled jumps, ``goto``, ``defer`` and ``go`` stay unmodelled). Scalar
``const`` declarations and reads are admitted: a constant expression can
never read a variable (the compiler rejects it before this reader runs),
so a scalar-typed ``constant`` binding always resolves to an empty
dependency set and the declaration itself writes nothing; ``iota`` is
dep-free too, while non-scalar constants stay gaps and grouped
``const ( ... )`` forms are a parser gap like grouped ``var``. A named
scalar result — ``func F(x) (r int64)`` — is an ordinary local
pre-initialised to the dep-free zero value; a bare ``return`` (legal
only with a named result) yields its current dependencies. Type
switches, ``select`` and every other
statement shape stay unsupported.
Scalar conversions ``T(e)`` are effect-free — the result inherits the
operand's dependencies; the type change itself (truncation, widening)
is not modelled. The pure builtins ``min``/``max`` union their
arguments' dependencies; ``len``/``cap`` additionally admit an
imported container ``var`` operand (``len(lib.VA)``) or an index
chain reaching a container-typed element of one (``len(lib.V2[i])``)
as a dep-free external read (the indexes' own dependencies carry),
and every other builtin stays opaque.
Compiler-resolved
bindings/calls supply identity; tree-sitter supplies syntax, never resolution.
``stale_dependents`` maps callee replacement to the summaries that must be
re-derived — recorded targets are source-anchored identities, so a replaced
callee never reuses its identity. Reports require the trusted producer and
reader described in go_type_snapshot.
No processes, imports, persistent caches or existing audit routes are invoked.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

from agent import control_flow
from agent.go_type_snapshot import (
    MAX_SOURCE_BYTES,
    PACKAGE_PROFILE as TYPE_PACKAGE_PROFILE,
    PROFILE as TYPE_PROFILE,
    TARGETS,
    _package_raws,
    ByteSpan,
    FileSpan,
    Function,
    GoType,
    GoPackageSnapshot,
    GoTypeSnapshot,
    PackageMember,
    SnapshotError,
    _boolean,
    _list,
    _string,
)

PROFILE = "mumei.go-scalar-parameter-deps/v1"
MAX_FUNCTIONS = 128
MAX_DEPTH = 48
# Manifest restoration caps only the wire shape: the analyzer emits a
# summary for every declared function (over-limit ones as analysis_limit
# gaps), so a valid manifest can far exceed MAX_FUNCTIONS.
MAX_MANIFEST_MEMBERS = 8192
MAX_EXPRESSION_NODES = 2048
_BINARY = frozenset(
    {
        "+", "-", "*", "/", "%", "&", "|", "^", "&^", "<<", ">>",
        "==", "!=", "<", "<=", ">", ">=", "&&", "||",
    }
)
_UNARY = frozenset({"+", "-", "!", "^", "&"})
# Store-loop sentinel: an assignment slot holding a `*lib.PV = v`
# deref member write — the stored value's dependencies fold into
# every escaped binding at store time.
_ALIAS_FOLD = object()
_COMPOUND_ASSIGN = frozenset(
    {"+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>=", "&^="}
)
_SCALAR_BASIC_TYPES = frozenset(
    {
        b"bool", b"int", b"int8", b"int16", b"int32", b"int64",
        b"uint", b"uint8", b"uint16", b"uint32", b"uint64", b"uintptr",
        b"byte", b"rune",
    }
)
_UNTYPED_SCALAR_CONSTS = frozenset(
    {"untyped int", "untyped rune", "untyped bool"}
)


def _scalar_const_type(t: Any) -> bool:
    """Whether a type fact is a scalar constant type in the fragment."""
    return t.kind in {"integer", "boolean"} or (
        t.kind == "untyped" and t.basic_name in _UNTYPED_SCALAR_CONSTS
    )


def _scalar_constant(binding: Any) -> bool:
    """A compile-time constant in the scalar fragment — reads carry no deps."""
    return binding.kind == "constant" and _scalar_const_type(binding.type)


@dataclass(frozen=True)
class SummaryGap:
    reason: str
    span: ByteSpan | FileSpan | None = None
    callee: str = ""

    def to_dict(self) -> dict:
        result = {"reason": self.reason, "span": _span_dict(self.span)}
        if self.callee:
            result["callee"] = self.callee
        return result

    @classmethod
    def from_dict(cls, value: Any) -> "SummaryGap":
        v = _manifest_record(value, ("reason", "span"), ("callee",))
        return cls(
            _string(v["reason"]),
            _span_from_dict(v["span"]),
            _string(v["callee"]) if "callee" in v else "",
        )


@dataclass(frozen=True)
class CallTransfer:
    span: ByteSpan | FileSpan
    target: str
    arguments: tuple[frozenset[int], ...]
    result: frozenset[int]
    # `imported` marks a `direct_import` call: the callee body is opaque to
    # the fragment, so its effects cannot be claimed `none`.
    imported: bool = False

    def to_dict(self) -> dict:
        result = {
            "span": _span_dict(self.span),
            "target": self.target,
            "arguments": [sorted(argument) for argument in self.arguments],
            "result": sorted(self.result),
        }
        if self.imported:
            result["imported"] = True
        return result

    @classmethod
    def from_dict(cls, value: Any) -> "CallTransfer":
        v = _manifest_record(
            value, ("span", "target", "arguments", "result"), ("imported",)
        )
        span = _span_from_dict(v["span"])
        _require_restore(span is not None)
        arguments = _list(v["arguments"])
        _require_restore(len(arguments) <= MAX_MANIFEST_MEMBERS)
        return cls(
            span,
            _string(v["target"]),
            tuple(_deps_from_list(a) for a in arguments),
            _deps_from_list(v["result"]),
            _boolean(v["imported"]) if "imported" in v else False,
        )


def _span_dict(span: ByteSpan | FileSpan | None) -> dict | None:
    if span is None:
        return None
    result = {}
    if type(span) is FileSpan:
        result["file"] = span.file
    elif type(span) is not ByteSpan:
        raise ValueError("summary serialization requires a declared span")
    result["start"], result["end"] = span.start, span.end
    return result


def _type_dict(t: GoType) -> dict:
    result = {
        "kind": t.kind,
        "basic_name": t.basic_name,
        "bit_width": t.bit_width,
        "signed": t.signed,
        "type_id": t.type_id,
    }
    if t.elem is not None:
        result["elem"] = _type_dict(t.elem)
    if t.key is not None:
        result["key"] = _type_dict(t.key)
    return result


def _type_from_dict(value: Any, depth: int = 0) -> GoType:
    """Rebuild a declared type fact; every field is re-validated, none trusted."""
    _require_restore(depth <= MAX_DEPTH)
    v = _manifest_record(
        value,
        ("kind", "basic_name", "bit_width", "signed", "type_id"),
        ("elem", "key"),
    )
    signed = v["signed"]
    _require_restore(type(signed) is bool or signed is None)
    _require_restore(type(v["bit_width"]) is int and v["bit_width"] >= 0)
    return GoType(
        _string(v["kind"]),
        _string(v["basic_name"]),
        v["bit_width"],
        signed,
        _string(v["type_id"]),
        _type_from_dict(value["elem"], depth + 1) if "elem" in value else None,
        _type_from_dict(value["key"], depth + 1) if "key" in value else None,
    )


def _span_from_dict(value: Any) -> ByteSpan | FileSpan | None:
    """Rebuild a declared span. Offsets are metadata — no source to check them
    against here, so only shape and ordering are validated; a consumer that
    slices bytes must re-derive bounds itself."""
    if value is None:
        return None
    _require_restore(isinstance(value, dict))
    keys = set(value)
    if keys == {"start", "end"}:
        start, end = value["start"], value["end"]
        _require_restore(type(start) is int and type(end) is int and 0 <= start <= end)
        return ByteSpan(start, end)
    if keys == {"file", "start", "end"}:
        file, start, end = value["file"], value["start"], value["end"]
        _require_restore(
            type(file) is int
            and type(start) is int
            and type(end) is int
            and file >= -1
            and 0 <= start <= end
        )
        return FileSpan(file, start, end)
    _require_restore(False)


def _deps_from_list(value: Any) -> frozenset[int]:
    deps = _list(value)
    _require_restore(
        len(deps) <= MAX_MANIFEST_MEMBERS
        and all(type(d) is int and d >= 0 for d in deps)
    )
    return frozenset(deps)


def _require_restore(condition: bool) -> None:
    if not condition:
        raise SnapshotError("declared summary manifest is malformed")


def _manifest_record(value: Any, required: tuple[str, ...], optional: tuple[str, ...] = ()) -> dict:
    """Like `_record` but tolerant of the declared optional keys."""
    _require_restore(isinstance(value, dict))
    _require_restore(set(required) <= set(value) <= set(required) | set(optional))
    return value


@dataclass(frozen=True)
class FunctionSummary:
    binding_id: str
    key: str
    parameters: tuple[GoType, ...]
    result_type: GoType | None
    return_dependencies: frozenset[int] | None
    calls: tuple[CallTransfer, ...]
    gaps: tuple[SummaryGap, ...]
    # `pinned` names named/alias type identities this summary depends
    # on, beyond binding identities: the function's own declared
    # parameter/result type facts, every admitted member read or
    # conversion whose member type carries one, and every resolved
    # call's callee signature. The summary stays valid only while all
    # of them keep their identities, so `stale_dependents` flags it
    # when any is redeclared. Basic and unnamed types carry no identity
    # and pin nothing.
    pinned: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        return self.return_dependencies is not None and not self.gaps

    @property
    def effects(self) -> str:
        # A `direct_import` transfer means part of the call graph is an
        # opaque imported callee whose effects the fragment cannot bound.
        if not self.available or any(c.imported for c in self.calls):
            return "unknown"
        return "none_in_supported_fragment"

    @property
    def call_targets(self) -> frozenset[str]:
        """Callee identities the recorded calls were resolved against.

        Synthetic `<binding_id>/pointee` targets are excluded: they
        name an unnamed pointee no declaration can redeclare, so
        keeping one here would flag its summary stale forever —
        `stale_dependents` treats any target outside `known` as
        missing. (A real binding id is `sha256:<digest>:…`, never
        slash-suffixed.)
        """
        return frozenset(
            call.target
            for call in self.calls
            if not call.target.endswith("/pointee")
        )

    def to_dict(self) -> dict:
        """Detached declared metadata only — no bytes, no acceptance claim.

        `available`/`effects` recompute from the serialized fields rather
        than being stored: a manifest names what was declared, and the
        reader re-derives the same answers. `None` dependencies serialize
        as a missing field, never a null that could read as
        parameter-independent."""
        result = {
            "binding_id": self.binding_id,
            "key": self.key,
            "parameters": [_type_dict(t) for t in self.parameters],
            "calls": [call.to_dict() for call in self.calls],
            "gaps": [gap.to_dict() for gap in self.gaps],
        }
        if self.result_type is not None:
            result["result_type"] = _type_dict(self.result_type)
        if self.return_dependencies is not None:
            result["return_dependencies"] = sorted(self.return_dependencies)
        if self.pinned:
            result["pinned"] = list(self.pinned)
        return result

    @classmethod
    def from_dict(cls, value: Any) -> "FunctionSummary":
        """Rebuild a declared summary: strict shape, then the same invariants
        the analyzer maintains — dependencies are non-negative ordinals,
        member lists are bounded, and declared fields carry declared types.
        A restored summary is *declared* data: it still answers through
        `for_function`/`stale_dependents`, so a stale or foreign manifest
        cannot authorize reuse — only describe it."""
        v = _manifest_record(
            value,
            ("binding_id", "key", "parameters", "calls", "gaps"),
            ("result_type", "return_dependencies", "pinned"),
        )
        parameters = _list(v["parameters"])
        _require_restore(len(parameters) <= MAX_MANIFEST_MEMBERS)
        calls = _list(v["calls"])
        gaps = _list(v["gaps"])
        _require_restore(len(calls) + len(gaps) <= MAX_MANIFEST_MEMBERS)
        deps = (
            _deps_from_list(v["return_dependencies"])
            if "return_dependencies" in v
            else None
        )
        if deps is not None:
            _require_restore(all(d < len(parameters) for d in deps))
        pinned = (
            tuple(_string(p) for p in _list(v["pinned"]))
            if "pinned" in v
            else ()
        )
        _require_restore(
            len(pinned) <= MAX_MANIFEST_MEMBERS
            and len(set(pinned)) == len(pinned)
        )
        restored_calls = tuple(CallTransfer.from_dict(c) for c in calls)
        # Every dependency ordinal a call records must name a declared
        # parameter, just like `return_dependencies`.
        _require_restore(
            all(
                d < len(parameters)
                for c in restored_calls
                for argument in (*c.arguments, c.result)
                for d in argument
            )
        )
        return cls(
            _string(v["binding_id"]),
            _string(v["key"]),
            tuple(_type_from_dict(t) for t in parameters),
            _type_from_dict(v["result_type"]) if "result_type" in v else None,
            deps,
            restored_calls,
            tuple(SummaryGap.from_dict(g) for g in gaps),
            pinned,
        )


def _context(source: str, snapshot: GoTypeSnapshot) -> tuple[bytes, str]:
    try:
        raw = source.encode("utf-8")
    except UnicodeError:
        raise SnapshotError("Unsupported Go summary source encoding") from None
    if (
        len(raw) > MAX_SOURCE_BYTES
        or hashlib.sha256(raw).hexdigest() != snapshot.source_sha256
        or snapshot.profile != TYPE_PROFILE
        or snapshot.language_version != "go1.23"
        or snapshot.target_arch not in TARGETS
    ):
        raise SnapshotError("Go summary context unavailable or stale")
    payload = json.dumps(
        [PROFILE, control_flow.PROFILE, asdict(snapshot)],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return raw, hashlib.sha256(payload).hexdigest()


def _package_context(
    snapshot: GoPackageSnapshot, sources: "dict[str, str] | list[str]"
) -> tuple[tuple[bytes, ...], str]:
    try:
        raws = _package_raws(snapshot, sources)
    except (KeyError, TypeError, ValueError):
        raise SnapshotError("Go summary context unavailable or stale") from None
    if (
        snapshot.profile != TYPE_PACKAGE_PROFILE
        or snapshot.language_version != "go1.23"
        or snapshot.target_arch not in TARGETS
    ):
        raise SnapshotError("Go summary context unavailable or stale")
    payload = json.dumps(
        [PROFILE, control_flow.PROFILE, asdict(snapshot)],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return raws, hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class GoSummarySet:
    context_key: str
    functions: tuple[FunctionSummary, ...]
    # The gc target the set was derived for — `int`/`uintptr` widths are
    # arch-dependent while binding identities are not, so a manifest
    # must declare it for a reuse route to refuse a mismatched unit.
    target_arch: str | None = None
    profile: str = PROFILE

    def for_function(
        self, source: str, snapshot: GoTypeSnapshot, binding_id: str
    ) -> FunctionSummary:
        """Reject reuse after any source, target, compiler or report change."""
        if _context(source, snapshot)[1] != self.context_key:
            raise SnapshotError("Go summary context unavailable or stale")
        result = next((f for f in self.functions if f.binding_id == binding_id), None)
        if result is None:
            raise SnapshotError("Go function summary unavailable")
        return result

    def for_package_function(
        self,
        sources: "dict[str, str] | list[str]",
        snapshot: GoPackageSnapshot,
        binding_id: str,
    ) -> FunctionSummary:
        """The package-unit variant of `for_function` — same staleness rule."""
        if _package_context(snapshot, sources)[1] != self.context_key:
            raise SnapshotError("Go summary context unavailable or stale")
        result = next((f for f in self.functions if f.binding_id == binding_id), None)
        if result is None:
            raise SnapshotError("Go function summary unavailable")
        return result

    def stale_dependents(self, known: Iterable[str]) -> frozenset[str]:
        """Summaries resolved against a callee or pinned identity outside `known`.

        Binding identities carry the producing unit's source digest, so a
        replaced callee never reuses its identity: every summary that
        recorded a call to a target absent from `known`, or pinned an
        imported type identity absent from `known`, must be re-derived —
        and so must every summary that called one of those: a caller's
        summary encodes its callee's answer, so flagging propagates
        along recorded `call_targets` edges until a fixed point. The
        fragment rejects recursion, so call edges among recorded
        summaries are acyclic and the propagation terminates.
        Detection only — what to recompute is the host's call.
        """
        live = frozenset(known)
        stale = {
            f.binding_id
            for f in self.functions
            if any(
                target not in live for target in (*f.call_targets, *f.pinned)
            )
        }
        changed = True
        while changed:
            changed = False
            for f in self.functions:
                if f.binding_id not in stale and any(
                    target in stale for target in f.call_targets
                ):
                    stale.add(f.binding_id)
                    changed = True
        return frozenset(stale)

    def to_dict(self) -> dict:
        """The declared summary manifest under `mumei.go-scalar-parameter-deps/v1`.

        Detached metadata naming the context key the set was derived
        against plus each function's declared fields — a host can persist
        or hand it to a route, but it proves nothing: `for_function`
        still rejects reuse after any source/snapshot change and
        `stale_dependents` still flags dependents of replaced identities."""
        result = {
            "schema_version": PROFILE,
            "context_key": self.context_key,
            "functions": [f.to_dict() for f in self.functions],
        }
        if self.target_arch is not None:
            result["target_arch"] = self.target_arch
        return result

    @classmethod
    def from_dict(cls, value: Any) -> "GoSummarySet":
        """Rebuild a declared summary set under `mumei.go-scalar-parameter-deps/v1`.

        Strict shape at the boundary, constructor invariants inside: the
        schema name must match exactly, member lists stay bounded, function
        identities must not repeat. The restored set is declared data, not
        derived truth — `for_function`/`for_package_function` still gate on
        the live snapshot's context key and `stale_dependents` still flags
        dependents of replaced identities, so a foreign manifest can only
        describe reuse, never authorize it."""
        v = _manifest_record(
            value,
            ("schema_version", "context_key", "functions"),
            ("target_arch",),
        )
        _require_restore(v["schema_version"] == PROFILE)
        functions = _list(v["functions"])
        _require_restore(len(functions) <= MAX_MANIFEST_MEMBERS)
        restored = tuple(FunctionSummary.from_dict(f) for f in functions)
        _require_restore(len({f.binding_id for f in restored}) == len(restored))
        target_arch = (
            _string(v["target_arch"]) if "target_arch" in v else None
        )
        return cls(_string(v["context_key"]), restored, target_arch)


class _Unsupported(Exception):
    def __init__(
        self,
        reason: str,
        span: ByteSpan | FileSpan | None = None,
        callee: str = "",
    ):
        self.gap = SummaryGap(reason, span, callee)


def _span(node: Any) -> ByteSpan:
    return ByteSpan(node.start_byte, node.end_byte)


def _children(node: Any) -> list[Any]:
    return [c for c in node.named_children if c.type != "comment"]


def _syntax(raw: bytes) -> Any:
    try:
        from tree_sitter import Language, Parser
        import tree_sitter_go

        root = Parser(Language(tree_sitter_go.language())).parse(raw).root_node
        return None if root.has_error else root
    except (ImportError, ValueError, TypeError, RuntimeError):
        return None


def _key3(span: ByteSpan | FileSpan) -> tuple[int, int, int]:
    """Normalize a report span to (file, start, end) — file 0 for v1 reports."""
    return (
        span.file if isinstance(span, FileSpan) else 0,
        span.start,
        span.end,
    )


class _Builder:
    def __init__(
        self,
        raws: dict[int, bytes],
        snapshot: GoTypeSnapshot | GoPackageSnapshot,
        key: str,
        cfg_fn: Any,
    ):
        self.snapshot, self.key, self.cfg_fn = snapshot, key, cfg_fn
        self.bindings = {b.id: b for b in snapshot.bindings}
        # Package reports may declare the imported objects the unit
        # referenced; single-file snapshots never have them.
        self.members = {m.id: m for m in getattr(snapshot, "imported_members", ())}
        self.functions = {f.binding_id: f for f in snapshot.functions}
        self.references = {_key3(r.span): r for r in snapshot.references}
        self.calls = {_key3(c.span): c for c in snapshot.calls}
        self.blocks: dict[tuple[int, int, int], Any] = {}
        self.bindings_by_span = {_key3(b.span): b for b in snapshot.bindings}
        self.cache: dict[str, FunctionSummary] = {}
        self.active: set[str] = set()
        self.pinned: set[str] = set()
        # Bindings whose address escaped through `&x`: a later
        # `lib.PV = p; *lib.PV = v` may write through the member into
        # one of them, so deref member stores union the stored
        # value's dependencies into every escaped binding.
        self.escaped: set[str] = set()
        # Dependencies stored through any pointer write — `*p = v` or
        # `*lib.PV = v`. The pointee is untracked memory, but a later
        # dereference read may observe the stored value, so every
        # `*t`/`*lib.PV` read unions this set back in (the escaped set
        # alone drops the deps when nothing took `&x`).
        self.indirect_writes: frozenset[int] = frozenset()
        self.current_file = 0
        # Innermost enclosing loop/switch constructs, innermost last; an
        # unlabelled break or continue marks the frame it exits.
        self.frames: list[dict[str, Any]] = []
        self.raws = raws
        for file, raw in raws.items():
            root = _syntax(raw)
            if root is None:
                continue
            for node in root.named_children:
                if node.type not in {"function_declaration", "method_declaration"}:
                    continue
                name, body = (
                    node.child_by_field_name("name"),
                    node.child_by_field_name("body"),
                )
                if name is not None and body is not None:
                    self.blocks[(file, name.start_byte, name.end_byte)] = body

    def node_key(self, node: Any) -> tuple[int, int, int]:
        return (self.current_file, node.start_byte, node.end_byte)

    def _package_level(self, binding: Any) -> bool:
        """Whether the binding declares package scope — the packaged
        profile's file `-1` sentinel, or the whole-file span in the
        single-file profile. A function-local `var` the fragment does
        not track carries its function's scope, not the unit's."""
        scope = binding.scope
        if scope is None:
            return False
        if isinstance(scope, FileSpan):
            return scope.file == -1
        raw = self.raws.get(0)
        return raw is not None and scope.start == 0 and scope.end == len(raw)

    def _pointee_type(self, type_id: str) -> Any | None:
        """The named pointee a `type_id` names — an imported `type`
        member, or a package-local `type` binding. Local type
        declarations carry the same real identity (a file-digest
        embedded binding id), so `stale_dependents` stays honest
        either direction."""
        member = self.members.get(type_id)
        if member is not None and member.kind == "type":
            return member
        binding = self.bindings.get(type_id)
        if binding is not None and binding.kind == "type":
            return binding
        return None

    def _local_field(self, field_ref: Any) -> Any | None:
        """The struct field a `kind == \"local\"` reference names — a
        `variable` binding with `scope is None` (the field marker:
        package vars carry the unit scope, function vars the
        function's). Anything else — a method expression's receiver
        or a misresolved name — stays closed."""
        if field_ref is None or field_ref.kind != "local":
            return None
        binding = self.bindings.get(field_ref.binding_id)
        if (
            binding is not None
            and binding.kind == "variable"
            and binding.scope is None
        ):
            return binding
        return None

    def _is_local_composite(self, binding: Any) -> bool:
        """A package-local named composite value — `st := P{...}`.

        Named composite declarations (`struct`/`interface`/`chan`/
        `func` shapes) carry `type.kind == "unsupported"` plus a
        `type_id` naming the `type` declaration; unnamed composites
        (`struct{...}`, `[]T`, `map`, `string`) carry no `type_id`
        and stay closed. The binding's single dep set conflates all
        fields — a sound over-approximation in both directions. The
        named type's identity pins on every admit so `stale_dependents`
        flags the summary when the type is redeclared.
        """
        composite = (
            binding is not None
            and binding.type is not None
            and binding.type.kind == "unsupported"
            and bool(binding.type.type_id)
            and self._pointee_type(binding.type.type_id) is not None
        )
        if composite:
            self.pinned.add(binding.type.type_id)
        return composite

    def _field_identity(self, field_ref: Any) -> Any | None:
        """The field a selector's `field` reference declares — an
        imported `var` member or a local `variable` binding."""
        if field_ref is None:
            return None
        if field_ref.kind == "import":
            member = self.members.get(field_ref.binding_id)
            if member is not None and member.kind == "var":
                return member
            return None
        return self._local_field(field_ref)

    def _local_composite_base(
        self, node: Any, locals_: dict[str, frozenset[int]]
    ) -> tuple[Any, tuple[Any, ...]] | None:
        """The `(root reference, resolved fields)` of a selector
        chain `st.A.B` rooted at a tracked composite local.

        Every selector level must resolve to a declared field —
        a method value (`st.M` names a `func`, not a field) keeps
        the chain closed — and every intermediate field (all but
        the final one) must be non-pointer-typed: `st.A.B` on
        `A *P2` auto-dereferences memory the conflated dep set
        cannot represent, so the chain stays closed. The returned
        fields are outermost-first.
        """
        fields: list[Any] = []
        cur = node
        while cur is not None and cur.type == "selector_expression":
            fields.append(cur.child_by_field_name("field"))
            cur = cur.child_by_field_name("operand")
            while (
                cur is not None
                and cur.type == "parenthesized_expression"
            ):
                cur = next(
                    (c for c in cur.named_children if c.type != "comment"),
                    None,
                )
        if cur is None or cur.type != "identifier" or cur.text == b"_":
            return None
        ref = self.references.get(self.node_key(cur))
        if ref is None or ref.binding_id not in locals_:
            return None
        if not self._is_local_composite(self.bindings.get(ref.binding_id)):
            return None
        resolved: list[Any] = []
        for i, field in enumerate(fields):
            field_ref = (
                self.references.get(self.node_key(field))
                if field is not None
                else None
            )
            ident = self._field_identity(field_ref)
            if (
                ident is None
                or field is None
                or ident.name.encode("utf-8") != field.text
            ):
                return None
            if i > 0 and ident.type.kind == "pointer":
                return None
            resolved.append(ident)
        return ref, tuple(resolved)

    def _struct_fields(self, type_binding: Any) -> tuple[Any, ...]:
        """The field bindings declared directly inside a local named
        type's declaration — `V` and `Q` for
        `type P struct{ *Q; V int64 }`.

        Field bindings are the `variable` bindings with no scope; they
        appear in source order between their type's name span and the
        next top-level declaration in the same file. A field reached
        by promotion (`st.V` where V lives on embedded `Q`) binds
        under its own declaring type, so it never appears here —
        which is what lets the caller spot a write that must cross
        an embedded pointer. Returns () when the type declares no
        fields (`type Ptr *P` — a named pointer is not a struct).
        """
        span = type_binding.span
        boundary: int | None = None
        direct: list[Any] = []
        for b in self.bindings.values():
            if b.span.file != span.file or b.span.start <= span.end:
                continue
            is_field = b.kind == "variable" and b.scope is None
            if is_field:
                if boundary is None or b.span.start < boundary:
                    direct.append(b)
            elif boundary is None or b.span.start < boundary:
                boundary = b.span.start
        return tuple(
            b
            for b in direct
            if boundary is None or b.span.start < boundary
        )

    def _direct_field_chain(
        self, ref: Any, resolved_fields: tuple[Any, ...]
    ) -> bool:
        """Whether every resolved field of a tracked-composite store
        is a *direct* field of its container's declared type.

        `st.V = x` on `type P struct{ *Q }` resolves `V` to its own
        declaring type `Q` — the syntactic chain names no pointer,
        but the store crosses embedded `*Q` into memory the conflated
        dep set cannot represent. The same check closes `q.V = x` on
        `var q Ptr` where `type Ptr *P` names no fields at all. An
        imported or anonymous container cannot be enumerated, so a
        write through it stays closed — reads remain sound under
        conflation.
        """
        root_binding = self.bindings.get(ref.binding_id)
        if root_binding is None or root_binding.type is None:
            return False
        n = len(resolved_fields)
        for j in range(n):
            container_type = (
                resolved_fields[j + 1].type
                if j + 1 < n
                else root_binding.type
            )
            type_id = (
                container_type.type_id if container_type is not None else ""
            )
            if not type_id:
                return False
            type_binding = self._pointee_type(type_id)
            span = getattr(type_binding, "span", None)
            if not isinstance(span, FileSpan):
                return False
            direct = {f.id for f in self._struct_fields(type_binding)}
            if resolved_fields[j].id not in direct:
                return False
        return True

    def _package_member(self, selector_node: Any) -> PackageMember | None:
        """The imported member a `pkg.Name` selector names, or None.

        The operand is a package name, which is not a binding and carries
        no reference; the field resolves to an `import` reference whose
        declared member record classifies the object. A record that names
        a different object than the source token never widens a use.
        """
        operand = selector_node.child_by_field_name("operand")
        field = selector_node.child_by_field_name("field")
        ref = (
            self.references.get(self.node_key(field))
            if field is not None
            else None
        )
        member = (
            self.members.get(ref.binding_id)
            if ref is not None and ref.kind == "import"
            else None
        )
        if (
            operand is None
            or operand.type != "identifier"
            or self.references.get(self.node_key(operand)) is not None
            or field is None
            or member is None
            or member.name.encode("utf-8") != field.text
        ):
            return None
        return member

    def _imported_field_read(
        self, node: Any
    ) -> tuple[PackageMember, PackageMember, tuple[Any, ...]] | None:
        """The `(struct member, field member, index nodes)` triple
        `lib.VS.F` names.

        The operand resolves to an imported `var` member like a member
        read — `lib.VS`, `VS` under a dot import, or parentheses around
        either — and the selector's field resolves through its own
        `import` reference to the field's member record, exactly the
        resolution `_package_member` performs one level down. The
        field's record classifies the read: it must be a `var` member
        of scalar or pointer type. A non-struct operand, a promoted
        method's `func` member, or any unresolvable name returns None
        and keeps the expression closed.
        """
        operand = node.child_by_field_name("operand")
        field = node.child_by_field_name("field")
        if operand is None or field is None:
            return None
        index_nodes: list[Any] = []
        while operand.type == "parenthesized_expression":
            operand = next(
                (c for c in operand.named_children if c.type != "comment"),
                None,
            )
            if operand is None:
                return None
        base = None
        if operand.type == "selector_expression":
            base = self._package_member(operand)
        elif operand.type == "index_expression":
            # `lib.VSM[k].F` / `lib.VSS[i].F` — a field of a
            # container element reads external state like the member
            # itself. The element of the whole chain must exist (a
            # named struct resolves the field's own reference below;
            # an anonymous one cannot, and a scalar element is
            # uncompilable anyway).
            resolved = self._index_member(operand)
            if resolved is None:
                return None
            member, levels = resolved
            if member.kind != "var":
                return None
            fact = member.type
            for _ in range(levels + 1):
                fact = fact.elem if fact is not None else None
            if fact is None:
                return None
            index_nodes.append(operand.child_by_field_name("index"))
            inner = operand.child_by_field_name("operand")
            while True:
                while (
                    inner is not None
                    and inner.type == "parenthesized_expression"
                ):
                    inner = next(
                        (
                            c
                            for c in inner.named_children
                            if c.type != "comment"
                        ),
                        None,
                    )
                if inner is None or inner.type != "index_expression":
                    break
                index_nodes.append(inner.child_by_field_name("index"))
                inner = inner.child_by_field_name("operand")
            base = member
        elif operand.type == "identifier":
            ref = self.references.get(self.node_key(operand))
            if ref is not None and ref.kind == "import":
                candidate = self.members.get(ref.binding_id)
                if (
                    candidate is not None
                    and candidate.name.encode("utf-8") == operand.text
                ):
                    base = candidate
        if base is None or base.kind != "var":
            return None
        ref = self.references.get(self.node_key(field))
        field_member = (
            self.members.get(ref.binding_id)
            if ref is not None and ref.kind == "import"
            else None
        )
        if (
            field_member is None
            or field_member.name.encode("utf-8") != field.text
            or field_member.kind != "var"
            or field_member.type.kind not in {"integer", "boolean", "pointer"}
        ):
            return None
        return base, field_member, tuple(index_nodes)

    def _bound_field_read(
        self,
        node: Any,
        locals_: dict[str, frozenset[int]],
        params: dict[str, int],
    ) -> tuple[tuple[PackageMember, ...], PackageMember, Any] | None:
        """The `(pointee members, field member, root ref)` triple
        `t.F` names.

        `t.F` on a bound `*S` auto-dereferences a field of caller
        state — external like `lib.VS.F`, so the read is dep-free and
        records against the field's identity. The operand must be a
        bound identifier whose pointer fact names the pointee `type`
member, or one explicit dereference of one (`(*t).F` — the same
        auto-deref spelled out), possibly through intermediate
        pointer-typed selections (`t.W.N` walks field `W`'s `*W2`
        member to `W2`, then resolves `N` there) — every `type`
        member traversed is returned for pinning. The field resolves
        through its own `import` reference to a scalar-or-pointer
        `var` member, like the imported-struct-var path — or, for a
        package-local struct type, through the field's `local`
        reference to its `scope`-less `variable` binding. A promoted
        method's `func` member, a non-scalar field, a computed base,
        or any unresolvable name returns None.
        """
        operand = node.child_by_field_name("operand")
        field = node.child_by_field_name("field")
        if operand is None or field is None:
            return None
        resolved = self._bound_selector_pointees(operand, locals_, params)
        if resolved is None:
            return None
        pointees, root_ref = resolved
        field_ref = self.references.get(self.node_key(field))
        field_member = None
        if field_ref is not None and field_ref.kind == "import":
            field_member = self.members.get(field_ref.binding_id)
        else:
            field_member = self._local_field(field_ref)
        if (
            field_member is None
            or field_member.name.encode("utf-8") != field.text
            or field_member.kind not in {"var", "variable"}
            or field_member.type.kind not in {"integer", "boolean", "pointer"}
        ):
            return None
        return pointees, field_member, root_ref

    def _bound_selector_pointees(
        self,
        operand: Any,
        locals_: dict[str, frozenset[int]],
        params: dict[str, int],
    ) -> tuple[tuple[PackageMember, ...], Any] | None:
        """Every member the operand's pointer chain traverses, and
        the root bound identifier's reference.

        A bound identifier (`t`) or one explicit dereference (`*t`,
        with parentheses either side) contributes its pointee `type`
        member — or the local `type` binding it names — and supplies
        the root reference; a nested selection
        (`t.W`) recurses through `_bound_field_read` and extends the
        chain with the field's own member — pinned so redeclaring
        `W` flags the summary — followed by the field's pointee
        `type` member when the field is pointer-typed. The tuple's
        last element is always the deepest pointee. Anything else —
        a computed base, a double deref, a non-pointer field —
        returns None.
        """
        while operand.type == "parenthesized_expression":
            operand = next(
                (c for c in operand.named_children if c.type != "comment"),
                None,
            )
            if operand is None:
                return None
        if operand.type == "unary_expression":
            operator = operand.child_by_field_name("operator")
            if operator is None or operator.text != b"*":
                return None
            operand = operand.child_by_field_name("operand")
            while (
                operand is not None
                and operand.type == "parenthesized_expression"
            ):
                operand = next(
                    (c for c in operand.named_children if c.type != "comment"),
                    None,
                )
            if operand is None:
                return None
        if operand.type == "selector_expression":
            inner = self._bound_field_read(operand, locals_, params)
            if inner is None:
                return None
            inner_pointees, inner_field, root_ref = inner
            if (
                inner_field.type.kind != "pointer"
                or not inner_field.type.type_id
            ):
                return None
            pointee = self._pointee_type(inner_field.type.type_id)
            if pointee is None:
                return None
            return (*inner_pointees, inner_field, pointee), root_ref
        if operand.type != "identifier" or operand.text == b"_":
            return None
        ref = self.references.get(self.node_key(operand))
        if ref is None or (
            ref.binding_id not in locals_ and ref.binding_id not in params
        ):
            return None
        binding = self.bindings.get(ref.binding_id)
        if (
            binding is None
            or binding.type.kind != "pointer"
            or not binding.type.type_id
        ):
            return None
        pointee = self._pointee_type(binding.type.type_id)
        if pointee is None:
            return None
        return (pointee,), ref

    def _qualified_type_member(self, qualified_node: Any) -> PackageMember | None:
        """The imported member a `pkg.Name` qualified type names, or None.

        Same contract as `_package_member`, for the `qualified_type`
        shape (`package: pkg`, `name: T`) a `generic_type` instantiation
        uses instead of `selector_expression`.
        """
        if qualified_node is None or qualified_node.type != "qualified_type":
            return None
        package = qualified_node.child_by_field_name("package")
        name = qualified_node.child_by_field_name("name")
        ref = (
            self.references.get(self.node_key(name))
            if name is not None
            else None
        )
        member = (
            self.members.get(ref.binding_id)
            if ref is not None and ref.kind == "import"
            else None
        )
        if (
            package is None
            or package.type != "package_identifier"
            or self.references.get(self.node_key(package)) is not None
            or name is None
            or member is None
            or member.name.encode("utf-8") != name.text
        ):
            return None
        return member

    def _pin_type_node(self, node: Any) -> bool:
        """Pin every named identity a type expression names.

        Returns False for a signature, struct or interface literal or
        an unresolvable name — the admitting caller keeps the
        expression closed rather than admit an unpinned identity.
        Composite constructors (`*T`, `[]T`, maps, channels, …) pin
        every named identity their elements name. Predeclared and
        universe names pin nothing.
        """
        if node is None:
            return False
        if node.type in {
            "pointer_type",
            "slice_type",
            "array_type",
            "map_type",
            "channel_type",
        }:
            children = tuple(node.named_children)
            if node.type == "array_type":
                # `[2]T` — the length is not a type expression; only
                # the element contributes pinnable identities.
                length = node.child_by_field_name("length")
                if length is not None:
                    children = tuple(
                        c
                        for c in children
                        if (c.start_byte, c.end_byte, c.type)
                        != (length.start_byte, length.end_byte, length.type)
                    )
            return bool(children) and all(
                self._pin_type_node(elem) for elem in children
            )
        if node.type in {"type_elem", "parenthesized_type"}:
            inner = next(iter(node.named_children), None)
            return inner is not None and self._pin_type_node(inner)
        if node.type == "qualified_type":
            member = self._qualified_type_member(node)
            if member is None:
                return False
            self._pin_member_type(member)
            return True
        if node.type == "generic_type":
            inner = node.child_by_field_name("type")
            if inner is None or not self._pin_type_node(inner):
                return False
            type_args = node.child_by_field_name("type_arguments")
            if type_args is None:
                return True
            return all(
                self._pin_type_node(elem)
                for elem in type_args.named_children
            )
        if node.type == "type_identifier":
            ref = self.references.get(self.node_key(node))
            if ref is None:
                # A type name the report recorded no reference for is
                # unresolvable — admit nothing unpinned.
                return False
            if ref.kind == "universe":
                # `int64`, `error`, `any`, … — declared nowhere, nothing
                # to pin.
                return True
            if ref.kind == "import":
                member = self.members.get(ref.binding_id)
                if member is None or member.name.encode("utf-8") != node.text:
                    return False
                self._pin_member_type(member)
                return True
            binding = (
                self.bindings.get(ref.binding_id) if ref.binding_id else None
            )
            if binding is None or binding.kind != "type":
                return False
            if binding.type.type_id:
                self.pinned.add(binding.type.type_id)
            return True
        return False

    def result(
        self,
        fn: Function,
        dependencies: frozenset[int] | None = None,
        calls: tuple[CallTransfer, ...] = (),
        gaps: tuple[SummaryGap, ...] = (),
        pinned: tuple[str, ...] = (),
    ) -> FunctionSummary:
        key = hashlib.sha256((self.key + ":" + fn.binding_id).encode()).hexdigest()
        return FunctionSummary(
            fn.binding_id,
            key,
            tuple(p.type for p in fn.parameters),
            fn.results[0].type if len(fn.results) == 1 else None,
            dependencies,
            calls,
            gaps,
            pinned,
        )

    def _pin_member_type(self, member: PackageMember) -> None:
        """Pin an admitted member's declared named-type identity.

        The producer names an imported `Named`/`Alias` type by the
        identity the imported unit's own report assigns it, so pinning
        it lets `stale_dependents` flag this summary when the type —
        not just the member — is redeclared.
        """
        if member.type.type_id:
            self.pinned.add(member.type.type_id)

    def _composite_var_read(
        self,
        node: Any,
        member: PackageMember,
        transfers: list[CallTransfer],
    ) -> bool:
        """A composite imported `var` in a receiver position reads
        external state: dep-free with the member's imported transfer
        on record and its whole type pinned. False for scalar-typed
        members — those evaluate through the normal expression path
        (`lib.VP.PM` keeps its member-read shape)."""
        if member.type is None or member.type.kind in {
            "integer",
            "boolean",
            "pointer",
        }:
            return False
        self._pin_fact_identities(member.type)
        transfers.append(
            CallTransfer(
                FileSpan(self.current_file, node.start_byte, node.end_byte),
                member.id,
                (),
                frozenset(),
                imported=True,
            )
        )
        return True

    def _index_receiver_read(
        self,
        node: Any,
        fn: Function,
        params: dict[str, int],
        locals_: dict[str, frozenset[int]],
        transfers: list[CallTransfer],
        count: list[int],
        depth: int,
    ) -> frozenset[int] | None:
        """A composite *element* of an imported container in a
        receiver position — `lib.VSS[i].PF()` or `lib.VSM[k].PF()`, and
        the leading argument of a method expression — reads external
        state like the container itself: the receiver carries only the
        indexes' dependencies, records the container member's imported
        transfer, and pins the whole fact tree. Scalar-typed elements
        return None — they evaluate through the normal index-read
        path, which already carries the index dependencies."""
        inner = node
        while inner is not None and inner.type == "parenthesized_expression":
            inner = next(
                (c for c in inner.named_children if c.type != "comment"),
                None,
            )
        if inner is None or inner.type != "index_expression":
            return None
        resolved = self._index_member(inner)
        if resolved is None:
            return None
        member, levels = resolved
        if member.kind != "var":
            return None
        fact = member.type
        for _ in range(levels + 1):
            fact = fact.elem if fact is not None else None
        if fact is None or fact.kind in {"integer", "boolean", "pointer"}:
            return None
        index_nodes = [inner.child_by_field_name("index")]
        cur = inner.child_by_field_name("operand")
        while True:
            while cur is not None and cur.type == "parenthesized_expression":
                cur = next(
                    (c for c in cur.named_children if c.type != "comment"),
                    None,
                )
            if cur is None or cur.type != "index_expression":
                break
            index_nodes.append(cur.child_by_field_name("index"))
            cur = cur.child_by_field_name("operand")
        self.pinned.add(member.id)
        self._pin_fact_identities(member.type)
        transfers.append(
            CallTransfer(
                FileSpan(self.current_file, node.start_byte, node.end_byte),
                member.id,
                (),
                frozenset(),
                imported=True,
            )
        )
        deps = frozenset()
        for idx in reversed(index_nodes):
            if idx is None:
                raise _Unsupported("non_parameter_reference", _span(node))
            if idx.type in {
                "int_literal",
                "float_literal",
                "imaginary_literal",
                "rune_literal",
                "interpreted_string_literal",
                "raw_string_literal",
            }:
                # A literal index carries no dependencies — the
                # expression path resolves `true`/`false` instead, in
                # case the predeclared names are shadowed.
                continue
            deps |= self.expression(
                idx, fn, params, locals_, transfers, count, depth + 1
            )
        return deps

    def _pin_fact_identities(self, fact: Any) -> None:
        """Pin every named type identity inside a fact tree — each
        container level's own and key identities plus the terminal
        element's — so redeclaring any flags `stale_dependents`."""
        while fact is not None:
            if fact.type_id:
                self.pinned.add(fact.type_id)
            if fact.key is not None and fact.key.type_id:
                self.pinned.add(fact.key.type_id)
            fact = fact.elem

    def _imported_index_read(
        self,
        node: Any,
        fn: Function,
        params: dict[str, int],
        locals_: dict[str, frozenset[int]],
        transfers: list[CallTransfer],
        count: list[int],
        depth: int,
    ) -> frozenset[int]:
        # `lib.VA[i]` — an index read of an imported slice/array var,
        # and `lib.VM[k]` — the single-value read of an imported map
        # var. The element/value is external state like the container
        # var itself, so the result carries only the index's own
        # dependencies; the read still records the imported transfer
        # (`effects` reports `unknown`) and pins the declared
        # container, element and map-key identities so redeclaring any
        # flags the summary through `stale_dependents`. The element
        # must be scalar-or-pointer — reading a struct element produces
        # a value the fragment's model cannot hold. A nested index
        # chain (`lib.V2[i][j]` on `[][]int64`) descends one `elem`
        # fact per level and admits when the final element is scalar —
        # the result unions every level's index deps. Everything else
        # stays closed: strings have no container fact and a computed
        # operand (`f()[i]`) names no member. The comma-ok form
        # `v, ok := lib.VM[k]` unpacks a map member's pair at the
        # statement level and lands here as the same read, and
        # imported-state writes (`lib.VA[i] = v`) match the
        # imported-var-write rule.
        operand = node.child_by_field_name("operand")
        index = node.child_by_field_name("index")
        # `lib.VA[i][j]` — a nested index chain: the outer index reads
        # an element of the container the inner read yields, so each
        # level descends one `elem` fact. `indexes` collects every
        # index node outermost-first so evaluation can run in Go's
        # order (the inner operand chain evaluates first).
        indexes = [] if index is None else [index]
        inner = operand
        while True:
            while (
                inner is not None
                and inner.type == "parenthesized_expression"
            ):
                inner = next(
                    (
                        c
                        for c in inner.named_children
                        if c.type != "comment"
                    ),
                    None,
                )
            if inner is None or inner.type != "index_expression":
                break
            indexes.append(inner.child_by_field_name("index"))
            inner = inner.child_by_field_name("operand")
        member = None
        if inner is not None and inner.type == "selector_expression":
            member = self._package_member(inner)
        elif inner is not None and inner.type == "identifier":
            ref = self.references.get(self.node_key(inner))
            if ref is not None and ref.kind == "import":
                candidate = self.members.get(ref.binding_id)
                if (
                    candidate is not None
                    and candidate.name.encode("utf-8") == inner.text
                ):
                    member = candidate
        # Descend one `elem` fact per extra index level — `[][]T`
        # yields `[]T` then `T`. Every container's own named identity
        # pins at its level (a named `[]T` element, a map key).
        container_kinds = {"slice", "array", "map"}
        fact = member.type if member is not None else None
        for _ in range(len(indexes) - 1):
            if (
                fact is None
                or fact.kind not in container_kinds
                or fact.elem is None
            ):
                raise _Unsupported(
                    "non_parameter_reference", _span(node)
                )
            if fact.type_id:
                self.pinned.add(fact.type_id)
            if fact.key is not None and fact.key.type_id:
                self.pinned.add(fact.key.type_id)
            fact = fact.elem
        elem = (
            fact.elem
            if fact is not None and fact.kind in container_kinds
            else None
        )
        if (
            index is None
            or member is None
            or member.kind != "var"
            or fact is None
            or fact.kind not in container_kinds
            or elem is None
            or elem.kind not in {"integer", "boolean", "pointer"}
        ):
            raise _Unsupported("non_parameter_reference", _span(node))
        self._pin_member_type(member)
        if fact.type_id:
            # The innermost container's own named identity —
            # `[]NS`/`map[K]NS` levels the descent stops on — must
            # pin too, or redeclaring it flags nothing.
            self.pinned.add(fact.type_id)
        if elem.type_id:
            self.pinned.add(elem.type_id)
        key = fact.key
        if key is not None and key.type_id:
            self.pinned.add(key.type_id)
        transfers.append(
            CallTransfer(
                FileSpan(self.current_file, node.start_byte, node.end_byte),
                member.id,
                (),
                frozenset(),
                imported=True,
            )
        )
        deps = frozenset()
        for idx in reversed(indexes):
            if idx is None:
                raise _Unsupported(
                    "non_parameter_reference", _span(node)
                )
            if idx.type in {
                "int_literal",
                "float_literal",
                "imaginary_literal",
                "rune_literal",
                "interpreted_string_literal",
                "raw_string_literal",
            }:
                # A literal index carries no dependencies —
                # `lib.VM["k"]` reads the entry at a constant key
                # like any other modelled index shape.
                # `true`/`false` are excluded: Go allows shadowing
                # the predeclared constants as variable names, so
                # the node alone cannot prove a constant — the
                # expression path resolves the `universe` reference
                # (still dep-free) or the shadowing binding's deps.
                continue
            deps |= self.expression(
                idx, fn, params, locals_, transfers, count, depth + 1
            )
        return deps

    def _imported_container_member(
        self, node: Any
    ) -> PackageMember | None:
        """The imported `var` member a range/index operand names.

        A package-qualified name, a dot-imported name, or parentheses
        around either — and only a slice, array or map kind. Anything
        else (a computed operand, a member of another kind, a
        non-container var) resolves to no member and the caller falls
        back to the ordinary expression gate.
        """
        inner = node
        while inner is not None and inner.type == "parenthesized_expression":
            inner = next(
                (c for c in inner.named_children if c.type != "comment"),
                None,
            )
        member = None
        if inner is not None and inner.type == "selector_expression":
            member = self._package_member(inner)
        elif inner is not None and inner.type == "identifier":
            ref = self.references.get(self.node_key(inner))
            if ref is not None and ref.kind == "import":
                candidate = self.members.get(ref.binding_id)
                if (
                    candidate is not None
                    and candidate.name.encode("utf-8") == inner.text
                ):
                    member = candidate
        if (
            member is not None
            and member.kind == "var"
            and member.type.kind in {"slice", "array", "map"}
        ):
            return member
        return None

    def _bind_range_names(
        self,
        names: list[Any],
        scope: dict[str, frozenset[int]],
        params: dict[str, int],
        conditional: bool,
    ) -> None:
        """Bind `for` range names to dep-free (external-state) values.

        `_` slots skip; a fresh `:=` name uses the compiler's binding
        record (its declared type must be scalar-or-pointer — a map's
        string key or a struct element stays closed); an `=` name
        reuses the referenced binding through `_store`.
        """
        for name in names:
            if name.text == b"_":
                continue
            binding = self.bindings_by_span.get(self.node_key(name))
            if binding is not None:
                if binding.type.kind not in {
                    "integer",
                    "boolean",
                    "pointer",
                }:
                    raise _Unsupported(
                        "binding_unavailable", _span(name)
                    )
                scope[binding.id] = frozenset()
            else:
                ref = self.references.get(self.node_key(name))
                if ref is None or (
                    ref.binding_id not in scope
                    and ref.binding_id not in params
                ):
                    raise _Unsupported(
                        "binding_unavailable", _span(name)
                    )
                self._store(
                    scope, params, ref.binding_id, frozenset(), conditional,
                )

    def _bound_receiver_root(
        self,
        receiver: Any,
        locals_: dict[str, frozenset[int]],
        params: dict[str, int],
    ) -> Any | None:
        """The bound identifier at the root of a nested-selector
        receiver — `t` in `t.W` — or None. A single-level receiver
        (`t`, `lib.VS`) evaluates its own deps directly; only a
        chain resolved through `_bound_field_read` needs the root's
        accumulated write deps."""
        inner = receiver
        while inner is not None and inner.type == "parenthesized_expression":
            inner = next(
                (c for c in inner.named_children if c.type != "comment"),
                None,
            )
        if inner is None or inner.type != "selector_expression":
            return None
        resolved = self._bound_field_read(inner, locals_, params)
        if resolved is None:
            return None
        return resolved[2]

    def _index_member(
        self, node: Any
    ) -> tuple[PackageMember, int] | None:
        """The imported `var` member an index expression's operand
        chain names — `lib.VM`, `VM` under a dot import, or
        parentheses around either — plus the number of extra index
        levels the chain wraps it in (`lib.VM2[k1][k2]` descends
        one), or None."""
        inner = node.child_by_field_name("operand")
        levels = 0
        while True:
            while inner is not None and inner.type == "parenthesized_expression":
                inner = next(
                    (c for c in inner.named_children if c.type != "comment"),
                    None,
                )
            if inner is None or inner.type != "index_expression":
                break
            levels += 1
            inner = inner.child_by_field_name("operand")
        member = self._imported_member_operand(inner)
        if member is None:
            return None
        return member, levels

    def _imported_member_operand(self, node: Any) -> PackageMember | None:
        """The imported member a bare operand names — `lib.VM`, `VM`
        under a dot import, or parentheses around either — or None."""
        inner = node
        while inner is not None and inner.type == "parenthesized_expression":
            inner = next(
                (c for c in inner.named_children if c.type != "comment"),
                None,
            )
        if inner is not None and inner.type == "selector_expression":
            return self._package_member(inner)
        if inner is not None and inner.type == "identifier":
            ref = self.references.get(self.node_key(inner))
            member = (
                self.members.get(ref.binding_id)
                if ref is not None and ref.kind == "import"
                else None
            )
            if (
                member is not None
                and member.name.encode("utf-8") != inner.text
            ):
                member = None
            return member
        return None

    def _comma_ok_map_index(
        self, node: Any, width: int
    ) -> PackageMember | None:
        """The map member a `v, ok := lib.VM[k]` read targets.

        Comma-ok binds exactly two names — the value read and the
        presence flag — so only a two-name LHS on an index
        expression whose operand names an imported map `var`
        admits. A nested chain (`v, ok := lib.VM2[k1][k2]`) admits
        when the outermost index's own container is still a map —
        one `elem` descent per inner level, so the root may be any
        container (`v, ok := lib.V[i]["k"]` on a `[]map[K]V`). The
        read itself still goes through `_imported_index_read`, so
        the element's scalar-or-pointer classification and the pins
        apply unchanged.
        """
        if width != 2 or node is None or node.type != "index_expression":
            return None
        resolved = self._index_member(node)
        if resolved is None:
            return None
        member, levels = resolved
        if member.kind != "var":
            return None
        fact = member.type
        for _ in range(levels):
            fact = fact.elem if fact is not None else None
        if fact is None or fact.kind != "map":
            return None
        return member

    def _imported_member_write(
        self, node: Any
    ) -> tuple[PackageMember, tuple[Any, ...], bool] | None:
        """The imported member an assignment LHS stores into, or None.

        `lib.V = v`, `lib.VA[i] = v`, `lib.VS.f = v` and
        `*lib.PV = v` — and their dot-imported forms `V = v`,
        `VA[i] = v`, `VS.f = v`, `*PV = v` — mutate package state
        the dependency model does not follow: it tracks
        binding indices, never member contents, so the store carries
        no result dependency. The member's own identity becomes the
        recorded write target, the same way `t.f = v` records the
        base's declared type identity. The returned extras are index
        sub-expressions inside the LHS (`lib.VA[f()] = v`); they must
        still be evaluated for anything that could record a transfer
        or pin. The third element reports whether a `*` deref
        unwrapped the member — a deref store's value may land in an
        escaped binding, so the caller marks its slot for the
        store-time dependency fold. A LHS that resolves to no
        imported member — a bound local's field, a computed operand,
        an unknown name — returns None and keeps the statement
        closed. A deref through a pointer-typed *field* member,
        `*lib.VS.P = v`, resolves the field like a field read and
        records the field member's identity, pinning the base
        member's beside the pointee's.
        """
        while node is not None and node.type == "parenthesized_expression":
            node = next(
                (c for c in node.named_children if c.type != "comment"),
                None,
            )
        if node is None:
            return None
        if node.type == "identifier":
            # Dot-imported `V = v`: a bare `import` reference whose
            # record names the same object, exactly like a member read.
            ref = self.references.get(self.node_key(node))
            member = (
                self.members.get(ref.binding_id)
                if ref is not None and ref.kind == "import"
                else None
            )
            if member is None or member.name.encode("utf-8") != node.text:
                return None
            return member, (), False
        extras: list[Any] = []
        cur = node
        saw_deref = False
        member = None
        while cur is not None:
            if cur.type == "parenthesized_expression":
                cur = next(
                    (c for c in cur.named_children if c.type != "comment"),
                    None,
                )
                continue
            if cur.type == "unary_expression":
                # `*lib.PV = v` — a dereference store through an
                # imported pointer-typed var mutates package state
                # exactly like the direct member store. `&`, `!` and
                # the rest can never be store targets.
                operator = cur.child_by_field_name("operator")
                if operator is None or operator.text != b"*":
                    return None
                saw_deref = True
                cur = cur.child_by_field_name("operand")
                continue
            if cur.type == "selector_expression":
                member = self._package_member(cur)
                if member is not None:
                    break
                if saw_deref:
                    # `*lib.VS.P = v` — a store through an imported
                    # pointer-typed *field* member: the field resolves
                    # like a field read does, and the same staleness
                    # cover applies — the base member's identity pins
                    # beside the field's pointee.
                    pair = self._imported_field_read(cur)
                    if pair is not None:
                        base, field_member, index_nodes = pair
                        if (
                            field_member.type.kind == "pointer"
                            and (
                                field_member.type.type_id
                                or field_member.pointee_type_ids
                                is not None
                            )
                        ):
                            self.pinned.add(base.id)
                            self._pin_fact_identities(base.type)
                            # `*lib.VSS[f()].P = v` — the indexes inside
                            # the field operand still evaluate, so they
                            # join `extras` outermost-first like the
                            # chain's own index nodes.
                            extras.extend(index_nodes)
                            member = field_member
                            break
                cur = cur.child_by_field_name("operand")
                continue
            if cur.type == "index_expression":
                index = cur.child_by_field_name("index")
                if index is not None:
                    extras.append(index)
                cur = cur.child_by_field_name("operand")
                continue
            if cur.type == "identifier":
                # The operand chain bottomed out on a bare name — a
                # dot-imported `VS.f = v` or `VA[i] = v`.
                ref = self.references.get(self.node_key(cur))
                member = (
                    self.members.get(ref.binding_id)
                    if ref is not None and ref.kind == "import"
                    else None
                )
                if (
                    member is not None
                    and member.name.encode("utf-8") == cur.text
                ):
                    break
                member = None
            return None
        if member is None:
            return None
        if saw_deref and (
            member.type.kind != "pointer"
            or (
                not member.type.type_id
                and member.pointee_type_ids is None
            )
        ):
            # `*lib.V = v` on a non-pointer member cannot compile —
            # the pointer check keeps a tampered record from
            # smuggling a store past the gate. The stored type's
            # named identities must also pin: the pointer fact's
            # `type_id` IS a named pointee's identity, so `*lib.PV = v`
            # pins `T`, and `pointee_type_ids` covers deeper named
            # uses — `*lib.PPV` on `**T` pins `T`, while a fully
            # unnamed pointee (`*lib.PU` on `*int64`, `(*lib.PA)[i]`
            # on `*[4]int64`) resolves to the empty list the member's
            # own identity covers. An unresolvable pointee tree
            # (`*struct{F T}`) emits no key — an inner redeclaration
            # would slip past `stale_dependents` — so it stays closed.
            return None
        return member, tuple(extras), saw_deref

    def _record_member_write(
        self,
        lhs: Any,
        member: PackageMember,
        extras: tuple[Any, ...],
        fn: Function,
        params: dict[str, int],
        locals_: dict[str, frozenset[int]],
        transfers: list[CallTransfer],
        count: list[int],
    ) -> None:
        """Record an imported member write's mutation and index calls."""
        if member.kind != "var":
            # `lib.F`, `lib.K` and `lib.T` name no writable storage —
            # unreachable in compilable source, rejected anyway so a
            # tampered member record cannot smuggle a write through.
            raise _Unsupported("unsupported_statement", _span(lhs))
        self._pin_member_type(member)
        if member.pointee_type_ids:
            # A pointer var's deeper named uses — `**T` pins `T` so
            # `type T`'s redeclaration flags the stored write.
            self.pinned.update(member.pointee_type_ids)
        key = member.type.key
        if key is not None and key.type_id:
            # `map[K]V` — a named key's identity pins like the
            # element's does.
            self.pinned.add(key.type_id)
        elem = member.type.elem
        while elem is not None:
            # `[][]T` names its element type two levels down — every
            # level's identity pins so a redeclared `T` still flags
            # the summary stale.
            if elem.type_id:
                self.pinned.add(elem.type_id)
            elem = elem.elem
        transfers.append(
            CallTransfer(
                FileSpan(self.current_file, lhs.start_byte, lhs.end_byte),
                member.id,
                (),
                frozenset(),
                imported=True,
            )
        )
        # Extras were collected outermost-first while descending the
        # operand chain; Go evaluates indices inside-out — the inner
        # index of `lib.V2[f()][g()]` runs before `g()` — so a write
        # `f()` performs must already be visible when `g()`'s call
        # arguments record their dependencies.
        for extra in reversed(extras):
            # The index value is unused — the write lands in package
            # state — so only evaluation's side effects matter: calls,
            # conversions and imported member reads record transfers
            # and pins that `stale_dependents` later reads. An index
            # holding none of those (a literal, a bound name, pure
            # arithmetic) needs no evaluation at all; one that does
            # evaluates through the normal expression gate and keeps
            # the statement closed when its shape is unmodelled.
            if self._index_extra_effects(extra):
                self.expression(
                    extra, fn, params, locals_, transfers, count, 0
                )

    def _index_extra_effects(self, node: Any) -> bool:
        """Whether an index sub-expression's evaluation could record a
        transfer or pin — a call, or a name/selector that resolves to
        an imported member."""
        if node.type == "call_expression":
            return True
        if (
            node.type == "selector_expression"
            and self._package_member(node) is not None
        ):
            return True
        if node.type == "identifier":
            ref = self.references.get(self.node_key(node))
            if ref is not None and ref.kind == "import":
                return True
        return any(
            self._index_extra_effects(c) for c in _children(node)
        )

    def _opaque_write_target(
        self, node: Any, locals_: dict[str, frozenset[int]], params: dict[str, int]
    ) -> tuple[str, Any] | None:
        """An assignment LHS whose field store lands in caller state.

        `t.f` (a field selection — reachable in the fragment only
        through a pointer-typed parameter, since struct-typed bindings
        cannot exist) mutates memory the dependency model does not
        follow: the model tracks each binding's index, never the
        pointee's or field's contents. The write is admitted when the
        base is a bound parameter or local identifier carrying a
        declared named-type identity — that identity becomes the
        recorded write target, and the base's reference is returned
        with it so the caller can fold the stored value's dependencies
        back into the base binding (a later `t.M()` can observe the
        write). A nested selection `t.W.f` walks the operand chain
        through pointer-typed field members like the bound field
        read: every traversed member pins and the deepest pointee
        records the transfer. An imported member, a package var, an unbound name, or
        a base whose type declares no identity keeps the statement
        closed, matching the bare-identifier gate. A `(*t).f` base
        admits the same way — the explicit dereference spells out
        `t.f`'s auto-deref, and the field write still lands only in
        the pointee. A bare `*t` LHS is not admitted here: an `&x`
        alias makes an indirected store able to overwrite a tracked
        binding.
        """
        while node is not None and node.type == "parenthesized_expression":
            node = next(
                (c for c in node.named_children if c.type != "comment"),
                None,
            )
        if node is None or node.type != "selector_expression":
            return None
        base = node.child_by_field_name("operand")
        while base is not None and base.type == "parenthesized_expression":
            base = next(
                (c for c in base.named_children if c.type != "comment"),
                None,
            )
        if base is not None and base.type == "unary_expression":
            # `(*t).f` — one explicit dereference of the bound pointer
            # before the selection, the same auto-deref `t.f` spelled
            # out. `**t` and computed bases stay closed.
            operator = base.child_by_field_name("operator")
            if operator is None or operator.text != b"*":
                return None
            base = base.child_by_field_name("operand")
            while (
                base is not None
                and base.type == "parenthesized_expression"
            ):
                base = next(
                    (c for c in base.named_children if c.type != "comment"),
                    None,
                )
        if base is not None and base.type == "selector_expression":
            # `t.W.f = v` — the store lands a level deeper into
            # caller state: the operand chain resolves through
            # pointer-typed field members, every traversed member
            # pins, and the deepest pointee's identity records the
            # mutation. The root identifier's reference still takes
            # the stored value's dependencies.
            resolved = self._bound_selector_pointees(
                base, locals_, params
            )
            if resolved is not None:
                pointees, ref = resolved
                self.pinned.update(p.id for p in pointees)
                return pointees[-1].id, ref
            # `st.A.B = v` on a tracked local composite: the store
            # folds into st's conflated dep set — a local mutation,
            # so the empty identity records no transfer.
            local = self._local_composite_base(base, locals_)
            if local is None:
                return None
            ref, resolved_fields = local
            # Every field in the base's chain is *traversed* to reach
            # the store target — a pointer-typed one dereferences
            # caller memory the conflated set cannot represent, so
            # `st.A.B = v` on `A *P2` stays closed.
            if any(
                field.type.kind == "pointer"
                for field in resolved_fields
            ):
                return None
            # A field reached through an *embedded* pointer hides the
            # same traversal (`st.V` on `type P struct{ *Q }`, or the
            # written leaf `st.A.N` on `type A struct{ *Q }`), so the
            # leaf must resolve and every field must be a direct
            # field of its container's declared type.
            leaf_node = node.child_by_field_name("field")
            leaf_ref = (
                self.references.get(self.node_key(leaf_node))
                if leaf_node is not None
                else None
            )
            leaf = self._field_identity(leaf_ref)
            if (
                leaf is None
                or leaf_node is None
                or leaf.name.encode("utf-8") != leaf_node.text
                or not self._direct_field_chain(
                    ref, (leaf,) + resolved_fields
                )
            ):
                return None
            return "", ref
        if base is None or base.type != "identifier" or base.text == b"_":
            return None
        ref = self.references.get(self.node_key(base))
        if ref is None or (
            ref.binding_id not in locals_ and ref.binding_id not in params
        ):
            return None
        binding = self.bindings.get(ref.binding_id)
        if binding is None or not binding.type.type_id:
            return None
        if self._is_local_composite(binding):
            # `st.V = v` on a tracked local composite — the value
            # folds into st's dep set; no external mutation records.
            # The selected field must be a *direct* field of st's
            # declared type: `st.V` on `type P struct{ *Q }` resolves
            # to a promoted field whose store crosses the embedded
            # pointer, and `q.V` on `var q Ptr` (`type Ptr *P`) names
            # no local memory at all — both write into caller state.
            field_node = node.child_by_field_name("field")
            field_ref = (
                self.references.get(self.node_key(field_node))
                if field_node is not None
                else None
            )
            ident = self._field_identity(field_ref)
            if (
                ident is None
                or field_node is None
                or ident.name.encode("utf-8") != field_node.text
                or not self._direct_field_chain(ref, (ident,))
            ):
                return None
            return "", ref
        if binding.type.kind != "pointer":
            return None
        return binding.type.type_id, ref

    def _bound_pointer_write(
        self,
        node: Any,
        locals_: dict[str, frozenset[int]],
        params: dict[str, int],
    ) -> str | None:
        """A `*p = v` store through a bound pointer.

        `p := &x` may aim the pointer at any escaped binding — dep
        sets track binding indices, never pointee contents, so the
        store cannot be proven to miss tracked state. It admits only
        through the escaped-binding fold (the `_ALIAS_FOLD` sentinel
        the caller installs): unioning the stored value's deps into
        every escaped binding is the same over-approximation
        `*lib.PV = v` uses. Returns the declared pointee identity
        for the mutation's transfer record — or None when the LHS is
        not a bound-pointer dereference, the binding's pointer names
        no pointee (`*int64`), or the pointee names a non-scalar
        shape, matching the `*lib.PV` read's pointee classification.
        """
        cur = node
        while cur is not None and cur.type == "parenthesized_expression":
            cur = next(
                (c for c in cur.named_children if c.type != "comment"),
                None,
            )
        if cur is None or cur.type != "unary_expression":
            return None
        operator = cur.child_by_field_name("operator")
        if operator is None or operator.text != b"*":
            return None
        inner = cur.child_by_field_name("operand")
        while inner is not None and inner.type == "parenthesized_expression":
            inner = next(
                (c for c in inner.named_children if c.type != "comment"),
                None,
            )
        if inner is None or inner.type != "identifier":
            return None
        ref = self.references.get(self.node_key(inner))
        if ref is None or (
            ref.binding_id not in locals_ and ref.binding_id not in params
        ):
            return None
        binding = self.bindings.get(ref.binding_id)
        if binding is None or binding.type.kind != "pointer":
            return None
        if not binding.type.type_id:
            # A `p := &x` alias binds an unnamed `*int64` — no member
            # identity classifies the pointee, so the pointer fact's
            # own `elem` carries its kind. Scalar-or-pointer pointees
            # admit; composite shapes (`*[]int64`, `*struct{...}`)
            # stay closed, as does a fact recorded before `elem` was
            # emitted. The returned identity is per-binding — nothing
            # declared can ever redeclare it, so `stale_dependents`
            # can never falsely flag it.
            elem = binding.type.elem
            if (
                elem is None
                or elem.kind not in {"integer", "boolean", "pointer"}
            ):
                return None
            return f"{ref.binding_id}/pointee"
        target = self._pointee_type(binding.type.type_id)
        if (
            target is None
            or target.type.kind not in {"integer", "boolean", "pointer"}
        ):
            return None
        return binding.type.type_id

    def _imported_pointer_deref(
        self,
        node: Any,
        fn: Function,
        params: dict[str, int],
        locals_: dict[str, frozenset[int]],
        transfers: list[CallTransfer],
        count: int,
        depth: int,
    ) -> frozenset[int]:
        # `*lib.PV` — dereference read of an imported pointer-typed
        # var — and `*t` — dereference read of a bound pointer whose
        # declared pointee names an identity. The operand's own read
        # records the imported transfer for the member form; the
        # bound form records its own transfer against the pointee
        # identity because nothing else marks the external read. The
        # pointee must resolve to a scalar
        # or pointer shape: a named pointee is scalar when the `type`
        # member — or the unit's own `type` binding — it names is;
        # an unnamed one (`*int64`) classifies by
        # the pointer fact's own `elem`, and composite shapes
        # (`*[]int64`, `*struct{...}`) stay closed. Any other operand
        # — a computed pointer or a nested deref — stays closed too:
        # dep sets track binding indices, not
        # pointee contents.
        # Comments appear among a node's named children; they are not
        # operands.
        children = tuple(
            c for c in node.named_children if c.type != "comment"
        )
        operand = children[0] if len(children) == 1 else None
        inner = operand
        while inner is not None and inner.type == "parenthesized_expression":
            inner = next(
                (c for c in inner.named_children if c.type != "comment"),
                None,
            )
        member = None
        if inner is not None and inner.type == "selector_expression":
            member = self._package_member(inner)
            if member is None:
                # `*lib.VS2.P` — a pointer-typed *field* member:
                # resolve it like a field read and classify by the
                # field member's fact, pinning the base member's
                # identity beside the field's so redeclaring either
                # flags the summary.
                pair = self._imported_field_read(inner)
                if pair is not None and pair[1].type.kind == "pointer":
                    base, field_member, _ = pair
                    self.pinned.add(base.id)
                    self._pin_fact_identities(base.type)
                    member = field_member
        elif inner is not None and inner.type == "identifier":
            # A dot-imported `*PV` classifies by the declared member
            # exactly like `*lib.PV` — a bare `import` reference whose
            # record names the same object.
            ref = self.references.get(self.node_key(inner))
            if ref is not None and ref.kind == "import":
                candidate = self.members.get(ref.binding_id)
                if (
                    candidate is not None
                    and candidate.name.encode("utf-8") == inner.text
                ):
                    member = candidate
        bound_ref = None
        # A synthetic `<binding>/pointee` identity classifies an
        # unnamed pointee — no member lookup applies to it.
        named_pointee = True
        if member is not None:
            if member.kind != "var" or member.type.kind != "pointer":
                raise _Unsupported("non_parameter_reference", _span(node))
            pointee_id = member.type.type_id
            if not pointee_id:
                # An unnamed pointee still classifies by its declared
                # shallow kind — `*lib.PU` reads an `int64`, `*lib.PPV`
                # a `*T` — provided the pointee tree is fully
                # pinnable (`pointee_type_ids` present), which a
                # `*struct{ F T }` member fails. Non-scalar shapes
                # (`*[4]int64`, `*[]T`, `*struct`) stay closed like a
                # named struct pointee does.
                if member.pointee_type_ids is None or (
                    member.pointee_kind
                    not in {"integer", "boolean", "pointer"}
                ):
                    raise _Unsupported(
                        "non_parameter_reference", _span(node)
                    )
                self.pinned.update(member.pointee_type_ids)
        else:
            # `*t` — a dereference read of a bound pointer. The
            # pointee is memory the dep model never tracks, so the
            # read records an imported transfer against the declared
            # pointee identity (`effects` reports `unknown`) — while
            # the result still carries the binding's own
            # dependencies, the pointer's provenance. Only an
            # identifier operand admits — a computed pointer
            # (`*g()`) or a nested deref (`**t`) stays closed.
            if inner is None or inner.type != "identifier":
                raise _Unsupported("non_parameter_reference", _span(node))
            bound_ref = self.references.get(self.node_key(inner))
            if bound_ref is None or (
                bound_ref.binding_id not in locals_
                and bound_ref.binding_id not in params
            ):
                raise _Unsupported("non_parameter_reference", _span(node))
            binding = self.bindings.get(bound_ref.binding_id)
            if binding is None or binding.type.kind != "pointer":
                raise _Unsupported("non_parameter_reference", _span(node))
            pointee_id = binding.type.type_id
            if not pointee_id:
                # A `p := &x` alias produces an unnamed `*int64`
                # binding — classify the pointee by the pointer
                # fact's `elem` (scalar-or-pointer admits, matching
                # the named path; composite/absent pointees stay
                # closed). The synthetic per-binding identity below
                # can never be pinned nor redeclared, which is what
                # the write side does too.
                elem = binding.type.elem
                if (
                    elem is None
                    or elem.kind
                    not in {"integer", "boolean", "pointer"}
                ):
                    raise _Unsupported(
                        "non_parameter_reference", _span(node)
                    )
                pointee_id = f"{bound_ref.binding_id}/pointee"
                named_pointee = False
        if named_pointee:
            target = self._pointee_type(pointee_id) if pointee_id else None
            if (
                pointee_id
                and (
                    target is None
                    or target.type.kind
                    not in {"integer", "boolean", "pointer"}
                )
            ):
                raise _Unsupported("non_parameter_reference", _span(node))
        if bound_ref is not None:
            # The pointee read touches memory outside the fragment —
            # record it like an imported member read so `effects`
            # reports `unknown` and the pointee's identity covers the
            # read for `stale_dependents`/`call_targets`.
            transfers.append(
                CallTransfer(
                    FileSpan(
                        self.current_file,
                        node.start_byte,
                        node.end_byte,
                    ),
                    pointee_id,
                    (),
                    frozenset(),
                    imported=True,
                )
            )
        result = self.expression(
            operand, fn, params, locals_, transfers, count, depth + 1
        )
        for escaped_id in self.escaped:
            # The pointer may alias any binding an earlier `&x`
            # escaped — `p := &x; x = y; *p` reads x's CURRENT value,
            # so the result must carry the escaped binding's deps,
            # not only the pointer's provenance. No type check: a
            # `*A` pointer can alias an `A2 = T` binding even though
            # the facts record distinct type_id's for the aliases, so
            # every escaped binding unions in like the `*lib.PV = v`
            # write-side fold. The same may-read holds for `*lib.PV`
            # once `lib.PV = &x` could have pointed it at x.
            if escaped_id in locals_:
                result |= locals_[escaped_id]
            elif escaped_id in params:
                result |= {params[escaped_id]}
        # A `*p = v` store lands in memory no binding tracks, but this
        # read may observe exactly that stored value — union every
        # dependency ever stored through a pointer so the write is not
        # dropped when no `&x` escaped (`*t = v; return *t`).
        result |= self.indirect_writes
        return result

    def summarize(self, binding_id: str) -> FunctionSummary:
        fn = self.functions[binding_id]
        if binding_id in self.cache:
            return self.cache[binding_id]
        if binding_id in self.active:
            return self.result(fn, gaps=(SummaryGap("recursive_call_graph"),))
        if len(self.active) >= MAX_DEPTH:
            return self.result(fn, gaps=(SummaryGap("analysis_limit"),))
        self.active.add(binding_id)
        try:
            summary = self.body(fn)
        except _Unsupported as error:
            summary = self.result(fn, gaps=(error.gap,))
        finally:
            self.active.remove(binding_id)
        self.cache[binding_id] = summary
        return summary

    def body(self, fn: Function) -> FunctionSummary:
        if (
            fn.body is None
            or fn.method
            or fn.generic
            or fn.variadic
            or len(fn.results) != 1
            # Pointer-typed parameters/results are admitted too: the
            # dep model tracks the *binding's* index, not the pointee,
            # and every use still passes the expression gates — so a
            # `*lib.T` param unlocks method calls on it while derefs,
            # field access and address-of stay closed. The pointee's
            # named/alias identity arrives on `type_id` and pins like
            # any other signature type.
            or any(
                p.type.kind not in {"integer", "boolean", "pointer"}
                for p in (*fn.parameters, *fn.results)
            )
        ):
            raise _Unsupported("unsupported_signature", fn.body)
        binding = self.bindings.get(fn.binding_id)
        body_key = _key3(fn.body)
        block = self.blocks.get(_key3(binding.span)) if binding is not None else None
        if block is None:
            raise _Unsupported("syntax_or_parser_unavailable", fn.body)
        if (body_key[0], block.start_byte + 1, block.end_byte - 1) != body_key:
            raise _Unsupported("source_mapping_unavailable", fn.body)
        previous_file = self.current_file
        self.current_file = body_key[0]
        pending = [(block, 0)]
        visited = 0
        while pending:
            node, depth = pending.pop()
            visited += 1
            if depth >= MAX_DEPTH or visited > MAX_EXPRESSION_NODES:
                raise _Unsupported("analysis_limit", fn.body)
            pending.extend((child, depth + 1) for child in _children(node))
        cfg = self.cfg_fn(fn.binding_id)
        if cfg.graph is None:
            raise _Unsupported("cfg_unavailable", fn.body)
        statements = _children(block)
        if len(statements) == 1 and statements[0].type == "statement_list":
            statements = _children(statements[0])
        if not statements:
            raise _Unsupported("unsupported_body", fn.body)
        params = {p.binding_id: i for i, p in enumerate(fn.parameters) if p.binding_id}
        transfers: list[CallTransfer] = []
        count = [0]
        locals_: dict[str, frozenset[int]] = {}
        # A named result is an ordinary local pre-initialised to the zero
        # value — dep-free until a body statement writes to it.
        result_binding = fn.results[0].binding_id
        if result_binding:
            locals_[result_binding] = frozenset()
        deps: list[frozenset[int]] = [frozenset()]
        saw_return = [False]
        # The frame stack and the pinned set belong to this function
        # alone — a caller's exited frame and a callee's type pins must
        # never leak into (or be marked by) the other function
        # summarized mid-expression.
        saved_frames = self.frames
        saved_pinned = self.pinned
        saved_escaped = self.escaped
        saved_indirect = self.indirect_writes
        self.frames = []
        self.pinned = set()
        self.escaped = set()
        self.indirect_writes = frozenset()
        # The summary embeds the function's declared parameter and
        # result type facts, so the named/alias identities they carry
        # pin it directly: redeclaring one makes this summary's
        # recorded facts stale even when its binding identity is
        # unchanged. Callers pin the same identities again at each
        # admitted call site.
        for p in (*fn.parameters, *fn.results):
            if p.type.type_id:
                self.pinned.add(p.type.type_id)
        try:
            self._sequence(
                statements, fn, params, locals_, transfers, count, deps,
                saw_return, False,
            )
        finally:
            pinned = tuple(sorted(self.pinned))
            self.frames = saved_frames
            self.pinned = saved_pinned
            self.escaped = saved_escaped
            self.indirect_writes = saved_indirect
            self.current_file = previous_file
        if not saw_return[0]:
            raise _Unsupported("unsupported_body", fn.body)
        return self.result(
            fn,
            deps[0],
            tuple(sorted(transfers, key=lambda c: _key3(c.span))),
            pinned=pinned,
        )

    def _sequence(
        self,
        children: list[Any],
        fn: Function,
        params: dict[str, int],
        locals_: dict[str, frozenset[int]],
        transfers: list[CallTransfer],
        count: list[int],
        deps: list[frozenset[int]],
        saw_return: list[bool],
        conditional: bool,
    ) -> None:
        """Run a statement list, honouring exits earlier children record.

        Once the innermost loop-or-switch frame is marked exited by an
        unlabelled break/continue, every later statement is conditional —
        it may have been skipped, so its writes union like a branch join.
        """
        frame = self.frames[-1] if self.frames else None
        for child in children:
            if frame is not None and frame["exited"]:
                conditional = True
            self.statement(
                child, fn, params, locals_, transfers, count, deps,
                saw_return, conditional,
            )

    @staticmethod
    def _store(
        locals_: dict[str, frozenset[int]],
        params: dict[str, int],
        binding_id: str,
        value: frozenset[int],
        conditional: bool,
    ) -> None:
        if conditional:
            if binding_id in locals_:
                # The skipped path keeps the binding's CURRENT value —
                # not a parameter's original deps once it was reassigned.
                value = locals_[binding_id] | value
            elif binding_id in params:
                value = frozenset({params[binding_id]}) | value
        locals_[binding_id] = value

    def statement(
        self,
        node: Any,
        fn: Function,
        params: dict[str, int],
        locals_: dict[str, frozenset[int]],
        transfers: list[CallTransfer],
        count: list[int],
        deps: list[frozenset[int]],
        saw_return: list[bool],
        conditional: bool,
    ) -> None:
        count[0] += 1
        if count[0] > MAX_EXPRESSION_NODES:
            raise _Unsupported("analysis_limit", _span(node))
        kind = node.type
        if kind in {"block", "statement_list"}:
            self._sequence(
                _children(node), fn, params, locals_, transfers, count,
                deps, saw_return, conditional,
            )
            return
        if kind == "return_statement":
            expressions = _children(node)
            if len(expressions) == 1 and expressions[0].type == "expression_list":
                expressions = _children(expressions[0])
            if len(expressions) == 0:
                # A bare `return` is only legal with a named result — it
                # yields the result binding's current dependencies.
                result_id = (
                    fn.results[0].binding_id if len(fn.results) == 1 else ""
                )
                if not result_id:
                    raise _Unsupported("unsupported_return", _span(node))
                deps[0] |= locals_.get(result_id, frozenset())
            elif len(expressions) == 1:
                deps[0] |= self.expression(
                    expressions[0], fn, params, locals_, transfers, count, 0
                )
            else:
                raise _Unsupported("unsupported_return", _span(node))
            saw_return[0] = True
            return
        if kind == "short_var_declaration":
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            lefts = _children(left) if left is not None else []
            rights = _children(right) if right is not None else []
            if not lefts or any(l.type != "identifier" for l in lefts):
                raise _Unsupported("unsupported_statement", _span(node))
            if len(lefts) != len(rights):
                # `a, b := lib.F(x)` — a multi-valued imported call
                # unpacks one RHS into every LHS; each result carries
                # the same over-approximated dependency set, so a
                # single evaluation stores to all names. `v, ok :=
                # lib.VM[k]` binds the comma-ok pair the same way —
                # the presence flag conservatively takes the read's
                # dependencies too.
                if len(rights) != 1 or (
                    self._multi_result_call(rights[0], fn, len(lefts))
                    is None
                    and self._comma_ok_map_index(rights[0], len(lefts))
                    is None
                ):
                    raise _Unsupported("unsupported_statement", _span(node))
                values = [
                    self.expression(
                        rights[0], fn, params, locals_, transfers, count, 0
                    )
                ] * len(lefts)
            else:
                # RHS expressions evaluate in parallel against the pre-state
                # — `a, b := b, a` swaps — so all reads happen before any
                # store.
                values = [
                    self.expression(
                        rhs, fn, params, locals_, transfers, count, 0
                    )
                    for rhs in rights
                ]
            for lhs, value in zip(lefts, values):
                # `_` discards its value — the RHS was still evaluated.
                if lhs.text == b"_":
                    continue
                # `x, y := e1, e2` may reuse an existing `x` when at
                # least one name is new — go/types records a use for it,
                # not a fresh binding.
                binding = self.bindings_by_span.get(self.node_key(lhs))
                if binding is None:
                    ref = self.references.get(self.node_key(lhs))
                    if ref is not None and ref.binding_id:
                        binding = self.bindings.get(ref.binding_id)
                if binding is None or (
                    binding.type.kind
                    not in {
                        "integer",
                        "boolean",
                        # A `p := t` binding inherits the pointer fact: it
                        # still tracks one dep set, so the same stores apply.
                        "pointer",
                    }
                    # `st := P{...}` — a named composite local carries
                    # one conflated dep set for every field.
                    and not self._is_local_composite(binding)
                ):
                    raise _Unsupported("binding_unavailable", _span(node))
                self._store(locals_, params, binding.id, value, conditional)
            return
        if kind == "var_declaration":
            # Grouped `var (...)` declarations never reach here — the
            # grammar marks them has_error and the source is rejected as
            # `syntax_or_parser_unavailable` before statement dispatch.
            specs = [
                c
                for c in node.named_children
                if c.type == "var_spec"
            ]
            if not specs:
                raise _Unsupported("unsupported_statement", _span(node))
            for spec in specs:
                names: list[Any] = []
                value_nodes: list[Any] = []
                for i, child in enumerate(spec.children):
                    field = spec.field_name_for_child(i)
                    if field == "name":
                        names.append(child)
                    elif field == "value":
                        value_nodes.extend(_children(child))
                multi = (
                    len(names) != len(value_nodes)
                    and len(value_nodes) == 1
                    and (
                        self._multi_result_call(
                            value_nodes[0], fn, len(names)
                        )
                        is not None
                        or self._comma_ok_map_index(
                            value_nodes[0], len(names)
                        )
                        is not None
                    )
                )
                if not names or (
                    len(names) != len(value_nodes)
                    and value_nodes
                    and not multi
                ):
                    raise _Unsupported("unsupported_statement", _span(spec))
                # `var a, b T` without values is the zero value —
                # dep-free. With values the RHS evaluates in parallel
                # against the pre-state before any store; `var a, b =
                # lib.F(x)` unpacks one multi-valued imported call like
                # a short variable declaration.
                if multi:
                    values = [
                        self.expression(
                            value_nodes[0], fn, params, locals_,
                            transfers, count, 0,
                        )
                    ] * len(names)
                elif value_nodes:
                    values = [
                        self.expression(
                            rhs, fn, params, locals_, transfers,
                            count, 0,
                        )
                        for rhs in value_nodes
                    ]
                else:
                    values = [frozenset() for _ in names]
                for name, value in zip(names, values):
                    if name.text == b"_":
                        continue
                    binding = self.bindings_by_span.get(self.node_key(name))
                    if binding is None or (
                        binding.type.kind
                        not in {
                            "integer",
                            "boolean",
                            "pointer",
                        }
                        and not self._is_local_composite(binding)
                    ):
                        raise _Unsupported(
                            "binding_unavailable", _span(spec)
                        )
                    self._store(
                        locals_, params, binding.id, value, conditional
                    )
            return
        if kind == "const_declaration":
            # Grouped `const (...)` declarations never reach here — like
            # grouped vars the grammar marks them has_error. A spec
            # without a value (implicit iota repetition) is unmodelled.
            specs = [
                c for c in node.named_children if c.type == "const_spec"
            ]
            if not specs:
                raise _Unsupported("unsupported_statement", _span(node))
            for spec in specs:
                names: list[Any] = []
                value_nodes: list[Any] = []
                for i, child in enumerate(spec.children):
                    field = spec.field_name_for_child(i)
                    # `name` fields also cover the `,` separators of a
                    # multi-name spec — only identifiers declare bindings.
                    if field == "name":
                        if child.type == "identifier":
                            names.append(child)
                        elif child.type != ",":
                            raise _Unsupported(
                                "unsupported_statement", _span(spec)
                            )
                    elif field == "value":
                        value_nodes.extend(_children(child))
                if not names or len(names) != len(value_nodes):
                    raise _Unsupported("unsupported_statement", _span(spec))
                for name in names:
                    if name.text == b"_":
                        continue
                    binding = self.bindings_by_span.get(self.node_key(name))
                    if binding is None or not _scalar_constant(binding):
                        raise _Unsupported(
                            "binding_unavailable", _span(spec)
                        )
                # Constant expressions never read variables, so the
                # values bind nothing — evaluating them only checks
                # fragment legality and records any builtin transfers.
                for rhs in value_nodes:
                    self.expression(
                        rhs, fn, params, locals_, transfers, count, 0
                    )
            return
        if kind == "if_statement":
            condition = node.child_by_field_name("condition")
            consequence = node.child_by_field_name("consequence")
            if condition is None or consequence is None:
                raise _Unsupported("unsupported_statement", _span(node))
            initializer = node.child_by_field_name("initializer")
            # `if init; cond` runs a simple statement first — the same
            # mechanism as a for-clause initializer. A name it binds is a
            # fresh binding that is scoped to the statement and dropped
            # by the join below, so a shadowed outer name keeps its deps.
            scope = dict(locals_) if initializer is not None else locals_
            if initializer is not None:
                self.statement(
                    initializer, fn, params, scope, transfers, count,
                    deps, saw_return, conditional,
                )
            # The condition is evaluated but its dependencies cannot reach
            # the result: every fragment statement is effect-free.
            self.expression(
                condition, fn, params, scope, transfers, count, 0
            )
            # Branch-local bindings never escape their scope, matching the
            # compiler — a later reference simply would not resolve.
            # Reassignments of existing names join back by union: the
            # branch may not execute.
            branch = dict(scope)
            self._sequence(
                _children(consequence), fn, params, branch, transfers,
                count, deps, saw_return, conditional,
            )
            self._join(scope, branch, params)
            alternative = node.child_by_field_name("alternative")
            if alternative is not None:
                branch = dict(scope)
                if alternative.type == "if_statement":
                    self.statement(
                        alternative, fn, params, branch, transfers,
                        count, deps, saw_return, conditional,
                    )
                else:
                    self._sequence(
                        _children(alternative), fn, params, branch,
                        transfers, count, deps, saw_return, conditional,
                    )
                self._join(scope, branch, params)
            if initializer is not None:
                self._join(locals_, scope, params)
            return
        if kind == "assignment_statement":
            operator = node.child_by_field_name("operator")
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            lefts = _children(left) if left is not None else []
            rights = _children(right) if right is not None else []
            compound = operator is not None and operator.type in _COMPOUND_ASSIGN
            multi = (
                len(lefts) != len(rights)
                and len(rights) == 1
                and (
                    self._multi_result_call(rights[0], fn, len(lefts))
                    is not None
                    or self._comma_ok_map_index(rights[0], len(lefts))
                    is not None
                )
            )
            if (
                operator is None
                or (operator.type != "=" and not compound)
                or not lefts
                or (compound and len(lefts) != 1)
                or (len(lefts) != len(rights) and not multi)
            ):
                raise _Unsupported("unsupported_statement", _span(node))
            # Every LHS must be a bound identifier or `_` before any RHS
            # runs, matching the single-assignment check's error order.
            refs: list[Any] = []
            for lhs in lefts:
                if lhs.type == "identifier":
                    if lhs.text == b"_":
                        refs.append(None)
                        continue
                    ref = self.references.get(self.node_key(lhs))
                    if ref is None or (
                        ref.binding_id not in locals_
                        and ref.binding_id not in params
                    ):
                        # A dot-imported member write — `V = v` —
                        # mutates imported package state like
                        # `lib.V = v`; the member record decides.
                        member_write = self._imported_member_write(lhs)
                        if member_write is None:
                            # A package-level `var` — `G = v` —
                            # mutates package state the same way:
                            # external state no binding tracks, so the
                            # stored value's deps drop and the imported
                            # transfer marks `effects` unknown. The
                            # target is the var's binding identity —
                            # in `known`, so redeclaring it flags
                            # `stale_dependents`.
                            gvar = (
                                self.bindings.get(ref.binding_id)
                                if ref is not None and ref.binding_id
                                else None
                            )
                            if (
                                gvar is None
                                or gvar.kind != "variable"
                                or not self._package_level(gvar)
                                or gvar.type.kind
                                not in {"integer", "boolean", "pointer"}
                            ):
                                raise _Unsupported(
                                    "binding_unavailable", _span(lhs)
                                )
                            self._pin_fact_identities(gvar.type)
                            transfers.append(
                                CallTransfer(
                                    FileSpan(
                                        self.current_file,
                                        lhs.start_byte,
                                        lhs.end_byte,
                                    ),
                                    gvar.id,
                                    (),
                                    frozenset(),
                                    imported=True,
                                )
                            )
                            refs.append(None)
                            continue
                        member, extras, _ = member_write
                        self._record_member_write(
                            lhs, member, extras,
                            fn, params, locals_, transfers, count,
                        )
                        refs.append(None)
                        continue
                    refs.append(ref)
                    continue
                # `t.f = v` — a field store through a pointer-typed
                # parameter (struct-typed bindings cannot exist in the
                # fragment, so `t` can only be `*S` pointing into
                # caller state) mutates memory the dependency model
                # does not follow: it tracks bindings, never field
                # contents. The store itself carries no result
                # dependency — the RHS still evaluates for its calls
                # and is discarded — but it IS an external mutation,
                # so a zero-argument imported transfer against the
                # base's declared type identity records it, marking
                # `effects` unknown like an imported var read. A
                # `*t = v` dereference admits further below through
                # the escaped-binding fold: `p := &x` may aim the
                # store at a tracked local, so the union keeps it
                # sound.
                write_target = self._opaque_write_target(
                    lhs, locals_, params
                )
                if write_target is not None:
                    type_id, ref = write_target
                    # A local composite's field store reports no
                    # external mutation — the empty identity skips
                    # the transfer; only the dep fold applies.
                    if type_id:
                        transfers.append(
                            CallTransfer(
                                FileSpan(
                                    self.current_file,
                                    lhs.start_byte,
                                    lhs.end_byte,
                                ),
                                type_id,
                                (),
                                frozenset(),
                                imported=True,
                            )
                        )
                    # The store lands in the pointee's contents — a
                    # later `t.M()` may observe it — so the RHS's
                    # dependencies accumulate into the base binding
                    # rather than replacing them or being discarded.
                    refs.append((ref, True))
                    continue
                # An imported member write — `lib.V = v`,
                # `lib.VA[i] = v`, `lib.VS.f = v` — mutates package
                # state like the field write above mutates caller
                # state: external, so the recorded transfer marks
                # `effects` unknown, and the stored value's
                # dependencies drop with it because no binding
                # tracks member contents.
                member_write = self._imported_member_write(lhs)
                if member_write is not None:
                    member, extras, saw_deref = member_write
                    self._record_member_write(
                        lhs, member, extras,
                        fn, params, locals_, transfers, count,
                    )
                    # A `*lib.PV = v` store may land in any binding an
                    # earlier `&x` leaked into the member — mark the
                    # slot so the store loop unions the stored value's
                    # dependencies into every escaped binding.
                    refs.append(_ALIAS_FOLD if saw_deref else None)
                    continue
                # `*p = v` — a store through a bound pointer lands in
                # memory the dep model does not track: the pointee's
                # declared identity records the external mutation
                # (`effects` reports `unknown`), and the stored
                # value's dependencies fold into every escaped
                # binding because `p := &x` may have aimed the
                # pointer at any of them — the same approximation
                # `*lib.PV = v` uses.
                pointee_id = self._bound_pointer_write(
                    lhs, locals_, params
                )
                if pointee_id is not None:
                    transfers.append(
                        CallTransfer(
                            FileSpan(
                                self.current_file,
                                lhs.start_byte,
                                lhs.end_byte,
                            ),
                            pointee_id,
                            (),
                            frozenset(),
                            imported=True,
                        )
                    )
                    refs.append(_ALIAS_FOLD)
                    continue
                raise _Unsupported("unsupported_statement", _span(lhs))
            # Tuple assignment is parallel: every RHS evaluates against the
            # pre-state before any store lands, so `x, y = y, x` swaps each
            # name's original dependencies. `x, y = lib.F(a)` unpacks one
            # multi-valued imported call into every LHS.
            values = (
                [
                    self.expression(
                        rights[0], fn, params, locals_, transfers, count, 0
                    )
                ]
                * len(lefts)
                if multi
                else [
                    self.expression(
                        rhs, fn, params, locals_, transfers, count, 0
                    )
                    for rhs in rights
                ]
            )
            for ref, value in zip(refs, values):
                if ref is None:
                    continue
                if ref is _ALIAS_FOLD:
                    # `*lib.PV = v` writes through a member that an
                    # earlier `&x` may have aimed at a tracked binding:
                    # any escaped binding might be the pointee, so the
                    # stored value's dependencies union into all of
                    # them rather than dropping with the write. They
                    # also accumulate into `indirect_writes` — a later
                    # dereference read may observe this exact value
                    # even when no `&x` escaped.
                    self.indirect_writes |= value
                    for escaped_id in self.escaped:
                        self._store(
                            locals_, params, escaped_id, value, True
                        )
                    continue
                accumulating = compound
                if isinstance(ref, tuple):
                    # A `t.f = v` opaque write target: the pointee's
                    # contents gain the RHS's dependencies on top of
                    # whatever they already tracked.
                    ref, accumulating = ref
                if accumulating:
                    # `x op= e` reads the old value too — the result unions
                    # the binding's current dependencies with the RHS's.
                    if ref.binding_id in locals_:
                        value = locals_[ref.binding_id] | value
                    else:
                        value = frozenset({params[ref.binding_id]}) | value
                # Reassignment replaces the binding's dependencies; it never
                # declares a new variable. Inside a branch the caller's join
                # unions the new value back as a may-assignment.
                self._store(
                    locals_, params, ref.binding_id, value, conditional,
                )
            return
        if kind == "for_statement":
            body_node = node.child_by_field_name("body")
            clause = next(
                (
                    child
                    for child in node.named_children
                    if child != body_node
                ),
                None,
            )
            if body_node is None:
                raise _Unsupported("unsupported_statement", _span(node))
            # The loop variable and every binding made inside the body are
            # scoped to the loop — none of them escape, matching the compiler.
            scope = dict(locals_)
            update = None
            if clause is not None and clause.type == "range_clause":
                # Two operand families are reachable: an integer
                # (`for i := range e` yields one index variable) and
                # an imported container var (`for i := range lib.VA`,
                # `for k, v := range lib.VM` — the container lives in
                # package state, so iteration yields dep-free values
                # the loop body joins). Every other composite operand
                # cannot be produced by a supported binding. `for i :=`
                # binds a fresh scoped name; `for i =` reuses an
                # existing binding; `_` slots and the bare `for range`
                # form just evaluate.
                left = clause.child_by_field_name("left")
                right = clause.child_by_field_name("right")
                lefts = _children(left) if left is not None else []
                member = (
                    self._imported_container_member(right)
                    if right is not None
                    else None
                )
                if member is not None:
                    # Ranging an imported container reads package state:
                    # the values (index/key and element) carry no
                    # parameter deps — like an index read — while the
                    # read still records the imported transfer and pins
                    # the container, key and element identities. At
                    # most two names bind; the second (element) and a
                    # map's key must each hold a modelled type.
                    if len(lefts) > 2 or any(
                        l.type != "identifier" for l in lefts
                    ):
                        raise _Unsupported(
                            "unsupported_statement", _span(clause)
                        )
                    self._pin_member_type(member)
                    key = member.type.key
                    if key is not None and key.type_id:
                        self.pinned.add(key.type_id)
                    elem = member.type.elem
                    if elem is not None and elem.type_id:
                        self.pinned.add(elem.type_id)
                    transfers.append(
                        CallTransfer(
                            FileSpan(
                                self.current_file,
                                right.start_byte,
                                right.end_byte,
                            ),
                            member.id,
                            (),
                            frozenset(),
                            imported=True,
                        )
                    )
                    # Each name's declared type comes from the
                    # compiler's binding — scalar-or-pointer, matching
                    # the index-read rule (a struct element or a
                    # string map key stays closed).
                    self._bind_range_names(
                        lefts, scope, params, conditional
                    )
                else:
                    if right is None or len(lefts) > 1 or (
                        lefts and lefts[0].type != "identifier"
                    ):
                        raise _Unsupported(
                            "unsupported_statement", _span(clause)
                        )
                    rdeps = self.expression(
                        right, fn, params, scope, transfers, count, 0
                    )
                    if lefts and lefts[0].text != b"_":
                        binding = self.bindings_by_span.get(self.node_key(lefts[0]))
                        if binding is not None:
                            if binding.type.kind not in {"integer", "boolean", "pointer"}:
                                raise _Unsupported(
                                    "binding_unavailable", _span(lefts[0])
                                )
                            scope[binding.id] = rdeps
                        else:
                            ref = self.references.get(self.node_key(lefts[0]))
                            if ref is None or (
                                ref.binding_id not in scope
                                and ref.binding_id not in params
                            ):
                                raise _Unsupported(
                                    "binding_unavailable", _span(lefts[0])
                                )
                            self._store(
                                scope, params, ref.binding_id, rdeps, conditional,
                            )
            elif clause is not None and clause.type == "for_clause":
                init = clause.child_by_field_name("initializer")
                if init is not None:
                    self.statement(
                        init, fn, params, scope, transfers, count, deps,
                        saw_return, conditional,
                    )
                condition = clause.child_by_field_name("condition")
                if condition is not None:
                    self.expression(
                        condition, fn, params, scope, transfers, count, 0
                    )
                update = clause.child_by_field_name("update")
            elif clause is not None:
                # `for <expression> { ... }` — a condition-only loop.
                self.expression(clause, fn, params, scope, transfers, count, 0)
            # Iterate the body to a fixed point: a reassignment made on one
            # pass seeds the next, so dependencies propagating across
            # iterations are captured (this is a join, not an unroll — trip
            # counts are never modelled). Every widened entry only gains
            # parameter indexes, so widening is monotone over a bounded
            # universe; the pass cap is a defensive analysis limit.
            passes = 0
            frame = {"kind": "loop", "exited": False}
            self.frames.append(frame)
            try:
                while True:
                    mark = len(transfers)
                    frame["exited"] = False
                    inner = dict(scope)
                    self._sequence(
                        _children(body_node), fn, params, inner, transfers,
                        count, deps, saw_return, conditional,
                    )
                    if update is not None:
                        # The update runs after each pass so its writes
                        # seed the next iteration — an inc/dec is a
                        # dependency-preserving no-op, an assignment's
                        # RHS dependencies widen into the fixed point.
                        self.statement(
                            update, fn, params, inner, transfers, count,
                            deps, saw_return, conditional,
                        )
                    changed = False
                    for binding_id, binding_deps in inner.items():
                        if binding_id in scope:
                            if not binding_deps <= scope[binding_id]:
                                scope[binding_id] |= binding_deps
                                changed = True
                        elif binding_id in params:
                            scope[binding_id] = (
                                frozenset({params[binding_id]}) | binding_deps
                            )
                            changed = True
                    if not changed:
                        break
                    # Keep only the last pass's transfers: argument
                    # dependency sets widen across passes and earlier
                    # copies are stale.
                    del transfers[mark:]
                    passes += 1
                    if passes > len(scope) * (len(params) + 1):
                        raise _Unsupported("analysis_limit", _span(node))
            finally:
                self.frames.pop()
            # Loop-body reassignments join back by union: the loop may
            # execute zero or many times.
            self._join(locals_, scope, params)
            return
        if kind == "expression_switch_statement":
            initializer = node.child_by_field_name("initializer")
            # `switch init; tag` runs a simple statement first — any name
            # it binds is scoped to the switch, like a for-clause init.
            scope = dict(locals_) if initializer is not None else locals_
            if initializer is not None:
                self.statement(
                    initializer, fn, params, scope, transfers, count,
                    deps, saw_return, conditional,
                )
            value = node.child_by_field_name("value")
            if value is not None:
                # The tag is evaluated but its dependencies cannot reach the
                # result: every fragment statement is effect-free.
                self.expression(
                    value, fn, params, scope, transfers, count, 0
                )
            frame = {"kind": "switch", "exited": False}
            self.frames.append(frame)
            try:
                clauses = [
                    c for c in node.named_children
                    if c.type in {"expression_case", "default_case"}
                ]
                branch: dict[str, frozenset[int]] | None = None
                for index, clause in enumerate(clauses):
                    body = next(
                        (
                            c for c in clause.named_children
                            if c.type == "statement_list"
                        ),
                        None,
                    )
                    statements = (
                        _children(body)
                        if body is not None
                        else (
                            _children(clause)
                            if clause.type == "default_case"
                            else []
                        )
                    )
                    falls = (
                        bool(statements)
                        and statements[-1].type == "fallthrough_statement"
                    )
                    if falls:
                        if index == len(clauses) - 1:
                            raise _Unsupported(
                                "unsupported_fallthrough", _span(clause)
                            )
                        statements = statements[:-1]
                    for sub in clause.named_children:
                        if sub.type == "expression_list":
                            # Case guards are evaluated like the tag.
                            for guard in _children(sub):
                                self.expression(
                                    guard, fn, params, scope,
                                    transfers, count, 0,
                                )
                    if branch is None:
                        # Direct match, or the head of a new chain — the
                        # same fresh alternative doubles as the chain's
                        # first step when the clause falls through.
                        frame["exited"] = False
                        branch = dict(scope)
                        self._sequence(
                            statements, fn, params, branch, transfers,
                            count, deps, saw_return, conditional,
                        )
                        if not falls:
                            self._join(scope, branch, params)
                            branch = None
                        continue
                    # Fall-through target — the body runs twice: once in
                    # the carried chain scope (the fallthrough path, with
                    # `exited` preserved across the chain), once as a
                    # fresh alternative (the direct-match path, which
                    # skips the preceding clause's writes).
                    self._sequence(
                        statements, fn, params, branch, transfers,
                        count, deps, saw_return, conditional,
                    )
                    chain_exited = frame["exited"]
                    frame["exited"] = False
                    fresh = dict(scope)
                    self._sequence(
                        statements, fn, params, fresh, transfers,
                        count, deps, saw_return, conditional,
                    )
                    self._join(scope, fresh, params)
                    if falls:
                        frame["exited"] = chain_exited
                    else:
                        self._join(scope, branch, params)
                        branch = None
            finally:
                self.frames.pop()
            if initializer is not None:
                self._join(locals_, scope, params)
            return
        if kind == "labeled_statement":
            inner = [c for c in node.named_children if c.type != "label_name"]
            if len(inner) != 1:
                raise _Unsupported("unsupported_statement", _span(node))
            # A label with no labelled jumps is inert syntax — the wrapped
            # statement is processed normally; `break L`/`continue L`
            # inside it stay unsupported via the label check below.
            self.statement(
                inner[0], fn, params, locals_, transfers, count, deps,
                saw_return, conditional,
            )
            return
        if kind in {"inc_statement", "dec_statement"}:
            operands = _children(node)
            if len(operands) != 1:
                raise _Unsupported("unsupported_statement", _span(node))
            operand = operands[0]
            if operand.type == "identifier":
                ref = self.references.get(self.node_key(operand))
                if ref is not None and (
                    ref.binding_id in locals_ or ref.binding_id in params
                ):
                    # x++ / x-- change the value, never its dependencies.
                    return
            member_write = self._imported_member_write(operand)
            if member_write is not None:
                member, extras, _ = member_write
                # `lib.V++` mutates package state like `lib.V = v` —
                # the stored amount is external, so only the
                # mutation records.
                self._record_member_write(
                    operand,
                    member,
                    extras,
                    fn,
                    params,
                    locals_,
                    transfers,
                    count,
                )
                return
            if operand.type == "identifier":
                # `G++`/`G--` on a package-level `var` mutate package
                # state like `lib.V++`: provenance-preserving, only the
                # external mutation records against the var's identity.
                gvar = (
                    self.bindings.get(ref.binding_id)
                    if ref is not None and ref.binding_id
                    else None
                )
                if (
                    gvar is not None
                    and gvar.kind == "variable"
                    and self._package_level(gvar)
                    and gvar.type.kind
                    in {"integer", "boolean", "pointer"}
                ):
                    self._pin_fact_identities(gvar.type)
                    transfers.append(
                        CallTransfer(
                            FileSpan(
                                self.current_file,
                                operand.start_byte,
                                operand.end_byte,
                            ),
                            gvar.id,
                            (),
                            frozenset(),
                            imported=True,
                        )
                    )
                    return
            # `(*p)++` — an increment through a bound pointer mutates
            # the same untracked memory `*p = v` does, but is
            # provenance-preserving: an aliased binding keeps its own
            # deps across the store, so no fold is needed — only the
            # external mutation records.
            pointee_id = self._bound_pointer_write(
                operand, locals_, params
            )
            if pointee_id is not None:
                transfers.append(
                    CallTransfer(
                        FileSpan(
                            self.current_file,
                            operand.start_byte,
                            operand.end_byte,
                        ),
                        pointee_id,
                        (),
                        frozenset(),
                        imported=True,
                    )
                )
                return
            # `t.F++` — an increment through a bound field mutates the
            # pointee's caller memory like `t.F = v`, and records the
            # same identity. The stored value is the field's own —
            # external — so, like `(*p)++`, no dependency fold is
            # needed: the base binding's deps carry on unchanged.
            write_target = self._opaque_write_target(
                operand, locals_, params
            )
            if write_target is not None:
                type_id, _ref = write_target
                # `st.F++` on a local composite is provenance-
                # preserving and local — no transfer records.
                if type_id:
                    transfers.append(
                        CallTransfer(
                            FileSpan(
                                self.current_file,
                                operand.start_byte,
                                operand.end_byte,
                            ),
                            type_id,
                            (),
                            frozenset(),
                            imported=True,
                        )
                    )
                return
            raise _Unsupported(
                "binding_unavailable"
                if operand.type == "identifier"
                else "unsupported_statement",
                _span(node),
            )
        if kind in {"break_statement", "continue_statement"}:
            if any(c.type == "label_name" for c in node.named_children):
                raise _Unsupported("unsupported_statement", _span(node))
            if kind == "break_statement":
                # Unlabelled break exits the innermost loop or switch.
                if not self.frames:
                    raise _Unsupported("unsupported_statement", _span(node))
                self.frames[-1]["exited"] = True
            else:
                # Unlabelled continue exits the innermost loop — plus
                # every construct between here and it, such as an
                # enclosing switch clause.
                for frame in reversed(self.frames):
                    frame["exited"] = True
                    if frame["kind"] == "loop":
                        break
                else:
                    raise _Unsupported("unsupported_statement", _span(node))
            return
        if kind == "expression_statement":
            # A call (or receive) evaluated for its side channel and
            # discarded — only those are legal expression statements.
            # The call's transfer still records normally; receives can
            # never appear in-fragment, so the inner expression fails
            # closed on its own if it isn't a supported call.
            inner = _children(node)
            if len(inner) != 1:
                raise _Unsupported("unsupported_statement", _span(node))
            self.expression(
                inner[0], fn, params, locals_, transfers, count, 0
            )
            return
        raise _Unsupported("unsupported_statement", _span(node))

    def _multi_result_call(self, node: Any, fn: Any, arity: int) -> Any:
        """The recorded call when `node` is a multi-valued imported call.

        Only a `direct_import` record whose declared arity matches the
        tuple width admits `a, b := f()` — every other shape (a wrong
        arity, a non-import callee, a non-call RHS) stays closed.
        """
        while node is not None and node.type == "parenthesized_expression":
            inner = _children(node)  # comments are named children too
            node = inner[0] if len(inner) == 1 else None
        if node is None or node.type not in {
            "call_expression",
            # `lib.G[T](x)` — a single-type-arg instantiation parses as
            # a conversion shape; the recorded call is authoritative.
            "type_conversion_expression",
        }:
            return None
        call = self.calls.get(self.node_key(node))
        if (
            call is not None
            and call.owner == fn.binding_id
            and call.kind == "direct_import"
            and call.results == arity
        ):
            return call
        return None

    @staticmethod
    def _join(
        outer: dict[str, frozenset[int]],
        inner: dict[str, frozenset[int]],
        params: dict[str, int],
    ) -> None:
        """Union inner-scope reassignments back into the outer environment.

        Bindings created inside the inner scope never escape — only names
        that existed outside (lets or parameters) merge, and their
        dependencies union because the inner code path may not run.
        """
        for binding_id, deps in inner.items():
            if binding_id in outer:
                outer[binding_id] |= deps
            elif binding_id in params:
                # A reassigned parameter keeps its own dependency — the
                # branch may not run.
                outer[binding_id] = frozenset({params[binding_id]}) | deps

    def expression(
        self,
        node: Any,
        fn: Function,
        params: dict[str, int],
        locals_: dict[str, frozenset[int]],
        transfers: list[CallTransfer],
        count: list[int],
        depth: int,
    ) -> frozenset[int]:
        count[0] += 1
        if depth + len(self.active) >= MAX_DEPTH or count[0] > MAX_EXPRESSION_NODES:
            raise _Unsupported("analysis_limit", _span(node))
        kind = node.type
        children = _children(node)
        if kind in {"int_literal", "rune_literal"}:
            return frozenset()
        if kind in {"identifier", "true", "false", "iota"}:
            ref = self.references.get(self.node_key(node))
            # Reassigned names (including parameters) resolve through
            # `locals_` first — their latest dependencies live there.
            if ref is not None and ref.binding_id in locals_:
                return locals_[ref.binding_id]
            if ref is not None and ref.binding_id in params:
                return frozenset({params[ref.binding_id]})
            # `iota` is not a keyword — only the compiler's universe
            # reference proves the predeclared constant, never the name.
            if (
                ref is not None
                and ref.kind == "universe"
                and (kind in {"true", "false"} or node.text == b"iota")
            ):
                return frozenset()
            if ref is not None and ref.kind == "import":
                # A dot-imported `K`/`V` classifies by the declared
                # member exactly like a package-qualified `lib.K`/`lib.V`
                # read: a scalar constant is dep-free and a scalar `var`
                # records an opaque state-read transfer. Everything else
                # — functions, types, non-scalars, a missing record or a
                # record naming a different object — stays closed.
                member = self.members.get(ref.binding_id)
                if member is not None and member.name.encode("utf-8") == node.text:
                    if member.kind == "const" and _scalar_const_type(member.type):
                        self._pin_member_type(member)
                        return frozenset()
                    if member.kind == "var" and member.type.kind in {
                        "integer",
                        "boolean",
                        "pointer",
                    }:
                        self._pin_member_type(member)
                        transfers.append(
                            CallTransfer(
                                FileSpan(
                                    self.current_file,
                                    node.start_byte,
                                    node.end_byte,
                                ),
                                member.id,
                                (),
                                frozenset(),
                                imported=True,
                            )
                        )
                        return frozenset()
                raise _Unsupported("non_parameter_reference", _span(node))
            binding = (
                self.bindings.get(ref.binding_id)
                if ref is not None and ref.binding_id
                else None
            )
            if binding is not None:
                # Constants can never read variables — the compiler
                # rejects a non-constant right-hand side before this
                # reader runs — so a scalar const is always dep-free.
                if _scalar_constant(binding):
                    return frozenset()
                if binding.kind == "constant":
                    raise _Unsupported("binding_unavailable", _span(node))
                if (
                    binding.kind == "variable"
                    and self._package_level(binding)
                    and binding.type.kind in {"integer", "boolean", "pointer"}
                ):
                    # A package-level `var` — mutable state outside the
                    # parameter set — reads like an imported `lib.V`:
                    # dep-free for the value but not purity-proof, so
                    # the imported transfer marks `effects` unknown.
                    # The target is the var's own binding identity,
                    # which lives in `known` — a redeclared or removed
                    # var still flags `stale_dependents`, and the
                    # recorded dep set never claims a false
                    # staleness the way a synthetic identity would.
                    self._pin_fact_identities(binding.type)
                    transfers.append(
                        CallTransfer(
                            FileSpan(
                                self.current_file,
                                node.start_byte,
                                node.end_byte,
                            ),
                            ref.binding_id,
                            (),
                            frozenset(),
                            imported=True,
                        )
                    )
                    return frozenset()
            raise _Unsupported("non_parameter_reference", _span(node))
        if kind == "selector_expression":
            # `lib.K` — a package-qualified member read. Scalar constants
            # are dep-free, exactly like local constants. A scalar `var`
            # read is modelled like a zero-argument `direct_import`
            # transfer: the value derives from package state, not from any
            # parameter, and the `imported` flag reports `effects` as
            # `unknown` — the read is not purity-proof. The recorded
            # target is the member's own identity, so a regenerated report
            # for the imported unit still flags this summary via
            # `stale_dependents`. Non-scalar vars, functions and any read
            # without a matching declaration stay closed.
            member = self._package_member(node)
            if member is not None and member.kind == "var":
                if member.type.kind not in {"integer", "boolean", "pointer"}:
                    raise _Unsupported("non_parameter_reference", _span(node))
                self._pin_member_type(member)
                transfers.append(
                    CallTransfer(
                        FileSpan(
                            self.current_file,
                            node.start_byte,
                            node.end_byte,
                        ),
                        member.id,
                        (),
                        frozenset(),
                        imported=True,
                    )
                )
                return frozenset()
            if member is None:
                # `lib.VS.F` / `VS.F` — a field of an imported struct
                # var. The field is external state like the member
                # itself: the read is dep-free but records the imported
                # transfer against the field's own identity and pins
                # both records' named types, so redeclaring the struct
                # or the field's type flags the summary.
                # A field through an index chain (`lib.VSM[k].F`)
                # additionally carries the indexes' own dependencies —
                # a literal index carries none, like the read's own
                # `lib.VM["k"]` rule.
                field_index_deps = frozenset()
                operand = node.child_by_field_name("operand")
                while (
                    operand is not None
                    and operand.type == "parenthesized_expression"
                ):
                    operand = next(
                        (
                            c
                            for c in operand.named_children
                            if c.type != "comment"
                        ),
                        None,
                    )
                if operand is not None and operand.type == "index_expression":
                    indexes = [operand.child_by_field_name("index")]
                    inner = operand.child_by_field_name("operand")
                    while True:
                        while (
                            inner is not None
                            and inner.type == "parenthesized_expression"
                        ):
                            inner = next(
                                (
                                    c
                                    for c in inner.named_children
                                    if c.type != "comment"
                                ),
                                None,
                            )
                        if inner is None or inner.type != "index_expression":
                            break
                        indexes.append(inner.child_by_field_name("index"))
                        inner = inner.child_by_field_name("operand")
                    for idx in reversed(indexes):
                        if idx is None:
                            raise _Unsupported(
                                "unresolved_or_opaque_call", _span(node)
                            )
                        if idx.type in {
                            "int_literal",
                            "float_literal",
                            "imaginary_literal",
                            "rune_literal",
                            "interpreted_string_literal",
                            "raw_string_literal",
                        }:
                            continue
                        field_index_deps |= self.expression(
                            idx, fn, params, locals_, transfers, count,
                            depth + 1,
                        )
                pair = self._imported_field_read(node)
                if pair is not None:
                    base, field_member, _ = pair
                    # The transfer targets the field's identity; pin
                    # the base member's own identity too so redeclaring
                    # `VS` in its own file still flags the summary. An
                    # index base (`lib.VSM[k]`) pins the whole fact
                    # tree so the element's named type is covered.
                    self.pinned.add(base.id)
                    self._pin_fact_identities(base.type)
                    self._pin_member_type(field_member)
                    transfers.append(
                        CallTransfer(
                            FileSpan(
                                self.current_file,
                                node.start_byte,
                                node.end_byte,
                            ),
                            field_member.id,
                            (),
                            frozenset(),
                            imported=True,
                        )
                    )
                    return field_index_deps
                # `t.F` — a field read through a bound `*S`. Same
                # dep-free external-state model: the field's value is
                # caller memory the dep model never tracks (a bound
                # pointer can never alias a tracked composite — `&st`
                # on one stays closed — so no union is needed), the
                # transfer marks `effects` unknown, and redeclaring `S`
                # or the field's type flags the summary.
                bound = self._bound_field_read(node, locals_, params)
                if bound is not None:
                    pointees, field_member, _root_ref = bound
                    self.pinned.update(p.id for p in pointees)
                    self._pin_member_type(field_member)
                    transfers.append(
                        CallTransfer(
                            FileSpan(
                                self.current_file,
                                node.start_byte,
                                node.end_byte,
                            ),
                            field_member.id,
                            (),
                            frozenset(),
                            imported=True,
                        )
                    )
                    return frozenset()
                # `st.V` / `st.A.B` — a field of a tracked local
                # composite: the binding's dep set conflates every
                # field, so the read returns it whole. Local state —
                # no transfer records, nothing pins.
                local = self._local_composite_base(node, locals_)
                if local is not None:
                    ref, _fields = local
                    return locals_.get(ref.binding_id, frozenset())
            if (
                member is None
                or member.kind != "const"
                or not _scalar_const_type(member.type)
            ):
                raise _Unsupported("non_parameter_reference", _span(node))
            self._pin_member_type(member)
            return frozenset()
        if kind == "parenthesized_expression" and len(children) == 1:
            return self.expression(
                children[0], fn, params, locals_, transfers, count, depth + 1
            )
        if kind == "composite_literal":
            # `P{V: x}` — the declared type node contributes nothing;
            # the literal's stored elements union the result deps.
            # Whether the composite value may bind at all is the
            # declaration site's decision (`_is_local_composite`).
            body = node.child_by_field_name("body")
            if body is None:
                raise _Unsupported("unsupported_expression", _span(node))
            return self.expression(
                body, fn, params, locals_, transfers, count, depth + 1
            )
        if kind in {"literal_value", "literal_element"}:
            deps: frozenset[int] = frozenset()
            for child in children:
                deps |= self.expression(
                    child, fn, params, locals_, transfers, count,
                    depth + 1,
                )
            return deps
        if kind == "keyed_element":
            # A struct literal's key is a field name — it resolves to
            # the field's binding and is never evaluated. A map or
            # slice literal's key IS an expression: `M[K(x): 0]` runs
            # `K` for its side effect, so it evaluates exactly like
            # the `value` child does.
            value_node = node.child_by_field_name("value")
            if value_node is None:
                raise _Unsupported("unsupported_expression", _span(node))
            deps = self.expression(
                value_node, fn, params, locals_, transfers, count,
                depth + 1,
            )
            key_node = node.child_by_field_name("key")
            while (
                key_node is not None
                and key_node.type == "literal_element"
            ):
                key_node = next(
                    (
                        c
                        for c in key_node.named_children
                        if c.type != "comment"
                    ),
                    None,
                )
            if key_node is not None:
                key_ref = (
                    self.references.get(self.node_key(key_node))
                    if key_node.type == "identifier"
                    else None
                )
                if self._field_identity(key_ref) is None:
                    deps |= self.expression(
                        key_node, fn, params, locals_, transfers, count,
                        depth + 1,
                    )
            return deps
        if kind in {"binary_expression", "unary_expression"}:
            # `&x` is the one unary with pointer semantics: the result
            # inherits the operand's deps exactly like a `p := t` bind,
            # and anything not addressable fails the producer's own
            # type check. Binary `&` stays bitwise.
            operator = node.child_by_field_name("operator")
            allowed = _BINARY if kind == "binary_expression" else _UNARY
            if operator is None or operator.type not in allowed:
                if (
                    kind == "unary_expression"
                    and operator is not None
                    and operator.type == "*"
                ):
                    return self._imported_pointer_deref(
                        node, fn, params, locals_, transfers, count, depth
                    )
                raise _Unsupported("unsupported_operator", _span(node))
            if kind == "unary_expression" and operator.type == "&":
                # `&x` leaks a tracked binding's identity into an
                # untracked pointer: a later `lib.PV = p; *lib.PV = v`
                # can write through it, so the binding is marked
                # escaped for the deref-store dependency fold.
                operand = node.child_by_field_name("operand")
                # `&st` / `&st.V` on a tracked composite stays closed:
                # the dep-free bound-pointer field read never sees
                # st's conflated set, so letting a pointer alias it
                # would under-approximate the read.
                root = operand
                while root is not None and root.type in {
                    "parenthesized_expression",
                    "selector_expression",
                    "index_expression",
                }:
                    if root.type == "parenthesized_expression":
                        root = next(
                            (
                                c
                                for c in root.named_children
                                if c.type != "comment"
                            ),
                            None,
                        )
                    else:
                        root = root.child_by_field_name("operand")
                # `&P{...}` stays closed too: the literal carries the
                # initializer's deps, but the bound-pointer field read
                # reports dep-free — the fresh value's contents are
                # not caller memory, so admitting would understate.
                if root is not None and root.type == "composite_literal":
                    raise _Unsupported("unsupported_operator", _span(node))
                root_ref = (
                    self.references.get(self.node_key(root))
                    if root is not None and root.type == "identifier"
                    else None
                )
                if root_ref is not None and self._is_local_composite(
                    self.bindings.get(root_ref.binding_id)
                ):
                    raise _Unsupported("unsupported_operator", _span(node))
                ref = (
                    self.references.get(self.node_key(operand))
                    if operand is not None
                    else None
                )
                if ref is not None and (
                    ref.binding_id in locals_ or ref.binding_id in params
                ):
                    self.escaped.add(ref.binding_id)
            deps: frozenset[int] = frozenset()
            for child in children:
                deps |= self.expression(
                    child, fn, params, locals_, transfers, count, depth + 1
                )
            return deps
        if kind == "index_expression":
            return self._imported_index_read(
                node, fn, params, locals_, transfers, count, depth
            )
        if kind == "call_expression":
            call = self.calls.get(self.node_key(node))
            if (
                call is None
                or call.owner != fn.binding_id
                or call.kind
                not in {"direct_local", "direct_import", "conversion", "builtin"}
            ):
                raise _Unsupported("unresolved_or_opaque_call", _span(node))
            arguments_node = node.child_by_field_name("arguments")
            arguments = _children(arguments_node) if arguments_node is not None else []
            if tuple(self.node_key(arg) for arg in arguments) != tuple(
                _key3(a) for a in call.arguments
            ):
                raise _Unsupported("call_mapping_unavailable", _span(node), call.target)
            if call.kind == "conversion":
                # `T(e)` is effect-free for dependency purposes — the
                # result inherits the operand's dependencies; the type
                # change itself (truncation, widening) is not modelled.
                # The target must be a scalar type too: a conversion to
                # a non-scalar (e.g. `string(x)`) would let the result
                # flow into contexts that never bind it — like a `range`
                # operand — without ever hitting a binding check.
                # Declared types resolve through their binding's type;
                # universe type names carry no binding_id, so they are
                # matched against Go's fixed predeclared scalar set.
                function_node = node.child_by_field_name("function")
                while (
                    function_node is not None
                    and function_node.type == "parenthesized_expression"
                ):
                    function_node = next(
                        iter(function_node.named_children), None
                    )
                if (
                    function_node is not None
                    and function_node.type == "selector_expression"
                ):
                    # `lib.T(e)` — the conversion target is declared by
                    # the imported member record, not by a local binding.
                    # Only a record naming the same member as a scalar
                    # `type` declaration keeps the result in the
                    # fragment.
                    member = self._package_member(function_node)
                    scalar = (
                        member is not None
                        and member.kind == "type"
                        and member.type.kind in {"integer", "boolean"}
                    )
                    if scalar:
                        self._pin_member_type(member)
                else:
                    ref = (
                        self.references.get(self.node_key(function_node))
                        if function_node is not None
                        else None
                    )
                    if ref is not None and ref.kind == "import":
                        # `T(e)` on a dot-imported type name — the record
                        # must name the same member and declare a scalar
                        # `type`, exactly like `lib.T(e)`.
                        member = self.members.get(ref.binding_id)
                        scalar = (
                            member is not None
                            and member.kind == "type"
                            and function_node is not None
                            and member.name.encode("utf-8")
                            == function_node.text
                            and member.type.kind in {"integer", "boolean"}
                        )
                        if scalar:
                            self._pin_member_type(member)
                    elif ref is not None and ref.binding_id:
                        binding = self.bindings.get(ref.binding_id)
                        scalar = (
                            binding is not None
                            and binding.type.kind in {"integer", "boolean"}
                        )
                    else:
                        scalar = (
                            ref is not None
                            and ref.kind == "universe"
                            and function_node is not None
                            and function_node.text in _SCALAR_BASIC_TYPES
                        )
                if not scalar:
                    raise _Unsupported("binding_unavailable", _span(node))
                if len(arguments) != 1:
                    raise _Unsupported(
                        "unsupported_expression", _span(node)
                    )
                return self.expression(
                    arguments[0], fn, params, locals_, transfers, count,
                    depth + 1,
                )
            if call.kind == "builtin":
                # Only the pure builtins reachable in a scalar fragment
                # are admitted — the result unions every argument's
                # dependencies; `panic`, `append` and the rest stay
                # opaque. `len`/`cap` admit one extra shape: a single
                # argument naming an imported container `var`
                # (`len(lib.VA)`) or an index chain on one whose
                # element is itself a container (`len(lib.V2[i])`,
                # `len(lib.VM2["a"])` on a map-valued map) reads
                # external state like the member itself, so the result
                # is dep-free apart from the indexes' own dependencies
                # — the call still records the imported transfer and
                # pins the declared identities. Any other operand
                # (`len(xs)` on a binding, `len(f())`,
                # `len(lib.VS2.G)` on a field) stays opaque.
                function_node = node.child_by_field_name("function")
                while (
                    function_node is not None
                    and function_node.type == "parenthesized_expression"
                ):
                    function_node = next(
                        iter(function_node.named_children), None
                    )
                name = function_node.text if function_node is not None else b""
                if name not in {b"min", b"max", b"len", b"cap"}:
                    raise _Unsupported("unresolved_or_opaque_call", _span(node))
                if not arguments:
                    raise _Unsupported("unsupported_expression", _span(node))
                if name in {b"len", b"cap"}:
                    if len(arguments) != 1:
                        raise _Unsupported(
                            "unresolved_or_opaque_call", _span(node)
                        )
                    member = self._imported_member_operand(arguments[0])
                    fact = member.type if member is not None else None
                    index_deps = frozenset()
                    if member is None:
                        # `len(lib.V2[i])` — a container-typed element
                        # reached through an index chain on an imported
                        # var is external state like the var itself:
                        # the result is dep-free apart from the
                        # indexes' own dependencies, exactly like the
                        # index read the same chain admits.
                        operand = arguments[0]
                        while (
                            operand is not None
                            and operand.type
                            == "parenthesized_expression"
                        ):
                            operand = next(
                                (
                                    c
                                    for c in operand.named_children
                                    if c.type != "comment"
                                ),
                                None,
                            )
                        if (
                            operand is None
                            or operand.type != "index_expression"
                        ):
                            raise _Unsupported(
                                "unresolved_or_opaque_call", _span(node)
                            )
                        resolved = self._index_member(operand)
                        if resolved is None:
                            raise _Unsupported(
                                "unresolved_or_opaque_call", _span(node)
                            )
                        member, levels = resolved
                        # `_index_member` counts the levels *below*
                        # the outermost index — the element `len`
                        # reads sits one `elem` deeper still, so the
                        # whole chain descends `levels + 1` facts.
                        fact = member.type
                        for _ in range(levels + 1):
                            fact = (
                                fact.elem if fact is not None else None
                            )
                        indexes = [
                            operand.child_by_field_name("index")
                        ]
                        inner = operand.child_by_field_name("operand")
                        while True:
                            while (
                                inner is not None
                                and inner.type
                                == "parenthesized_expression"
                            ):
                                inner = next(
                                    (
                                        c
                                        for c in inner.named_children
                                        if c.type != "comment"
                                    ),
                                    None,
                                )
                            if (
                                inner is None
                                or inner.type != "index_expression"
                            ):
                                break
                            indexes.append(
                                inner.child_by_field_name("index")
                            )
                            inner = inner.child_by_field_name("operand")
                        for idx in reversed(indexes):
                            if idx is None:
                                raise _Unsupported(
                                    "unresolved_or_opaque_call",
                                    _span(node),
                                )
                            if idx.type in {
                                "int_literal",
                                "float_literal",
                                "imaginary_literal",
                                "rune_literal",
                                "interpreted_string_literal",
                                "raw_string_literal",
                            }:
                                # A literal index carries no
                                # dependencies, like the index read's
                                # rule for `lib.VM["k"]`.
                                continue
                            index_deps |= self.expression(
                                idx, fn, params, locals_,
                                transfers, count, depth + 1,
                            )
                    if member is None or member.kind != "var":
                        raise _Unsupported(
                            "unresolved_or_opaque_call", _span(node)
                        )
                    if not (
                        fact is not None
                        and (
                            fact.kind in {"slice", "array", "map"}
                            or (
                                fact.kind == "unsupported"
                                and fact.basic_name == "string"
                            )
                        )
                    ):
                        raise _Unsupported(
                            "unresolved_or_opaque_call", _span(node)
                        )
                    self._pin_fact_identities(member.type)
                    transfers.append(
                        CallTransfer(
                            FileSpan(
                                self.current_file,
                                node.start_byte,
                                node.end_byte,
                            ),
                            member.id,
                            (),
                            frozenset(),
                            imported=True,
                        )
                    )
                    return index_deps
                deps = frozenset()
                for arg in arguments:
                    deps |= self.expression(
                        arg, fn, params, locals_, transfers, count,
                        depth + 1,
                    )
                return deps
            if call.kind == "direct_import":
                receiver = None
                if call.method:
                    # `recv.M(args)` — the callee is a method on an
                    # imported named type; the receiver expression is
                    # evaluated like an argument (its read may itself
                    # record a member transfer), and its deps join the
                    # result.
                    function_node = node.child_by_field_name("function")
                    while (
                        function_node is not None
                        and function_node.type == "parenthesized_expression"
                    ):
                        function_node = next(
                            iter(function_node.named_children), None
                        )
                    if (
                        function_node is None
                        or function_node.type != "selector_expression"
                    ):
                        raise _Unsupported(
                            "call_mapping_unavailable",
                            _span(node),
                            call.target,
                        )
                    receiver = function_node.child_by_field_name("operand")
                    if receiver is None:
                        raise _Unsupported(
                            "call_mapping_unavailable",
                            _span(node),
                            call.target,
                        )
                return self._direct_import_call(
                    call, arguments, fn, params, locals_, transfers,
                    count, depth, receiver=receiver,
                )
            target = self.functions.get(call.target)
            if target is None or len(arguments) != len(target.parameters):
                raise _Unsupported("callee_unavailable", _span(node), call.target)
            # Even unused arguments are evaluated and must have supported effects.
            actual = tuple(
                self.expression(
                    arg, fn, params, locals_, transfers, count, depth + 1
                )
                for arg in arguments
            )
            callee = self.summarize(call.target)
            if not callee.available:
                reason = (
                    "recursive_call_graph"
                    if any(g.reason == "recursive_call_graph" for g in callee.gaps)
                    else "callee_unsupported"
                )
                raise _Unsupported(reason, _span(node), call.target)
            assert callee.return_dependencies is not None
            result = frozenset(
                i for parameter in callee.return_dependencies for i in actual[parameter]
            )
            # The callee's declared named-type signature identities pin
            # exactly like an imported callee's: a local type's identity
            # already churns with its declaring file, while an imported one
            # (a local `func G(y lib.T)` parameter) would otherwise leave
            # this summary looking current after `T` is redeclared.
            for p in (*target.parameters, *target.results):
                if p.type.type_id:
                    self.pinned.add(p.type.type_id)
            # The callee's effect opacity propagates: a local callee that
            # itself performs imported transfers leaves this caller's
            # effects unbounded the same way a direct_import does.
            transfers.append(
                CallTransfer(
                    call.span,
                    call.target,
                    actual,
                    result,
                    imported=callee.effects == "unknown",
                )
            )
            if callee.effects == "unknown":
                # An effectful local callee may store through an `&x`
                # argument — its `*p = v` writes land in memory no
                # binding points back at, so `x` conservatively gains
                # every argument's deps like an imported call's.
                self._store_call_writes(
                    arguments,
                    frozenset().union(*actual) if actual else frozenset(),
                    locals_,
                    params,
                )
            return result
        if kind == "type_conversion_expression":
            # tree-sitter parses `lib.G[T](args)` — an explicit
            # instantiation of an imported generic function — in a
            # conversion shape, and `lib.S[T](x)` — an instantiated
            # generic *type* conversion — the same way. The producer's
            # call classification is authoritative: a `direct_import`
            # record admits the instantiated callee, a `conversion`
            # record admits the instantiated type conversion when the
            # target names a scalar imported member and every named
            # identity inside its type arguments pins.
            call = self.calls.get(self.node_key(node))
            if (
                call is None
                or call.owner != fn.binding_id
                or call.kind not in {"direct_import", "conversion"}
            ):
                raise _Unsupported("unsupported_expression", _span(node))
            operand = node.child_by_field_name("operand")
            if operand is None:
                raise _Unsupported("unsupported_expression", _span(node))
            arguments = (
                _children(operand)
                if operand.type == "expression_list"
                else [operand]
            )
            if tuple(self.node_key(arg) for arg in arguments) != tuple(
                _key3(a) for a in call.arguments
            ):
                raise _Unsupported(
                    "call_mapping_unavailable", _span(node), call.target
                )
            if call.kind == "direct_import":
                return self._direct_import_call(
                    call, arguments, fn, params, locals_, transfers,
                    count, depth,
                )
            # `lib.S[T…](x)` — an instantiated type conversion, which is
            # effect-free like any `T(e)`: the result inherits the
            # operand's dependencies. The conversion target must name a
            # scalar imported member (`type S[A any] int64`); a
            # composite underlying or an unpinnable name anywhere in the
            # type expression keeps it closed.
            type_node = node.child_by_field_name("type")
            member = (
                self._qualified_type_member(
                    type_node.child_by_field_name("type")
                )
                if type_node is not None
                and type_node.type == "generic_type"
                else None
            )
            if (
                member is None
                or member.kind != "type"
                or member.type.kind not in {"integer", "boolean"}
                or not self._pin_type_node(type_node)
            ):
                raise _Unsupported("binding_unavailable", _span(node))
            if len(arguments) != 1:
                raise _Unsupported(
                    "unsupported_expression", _span(node)
                )
            return self.expression(
                arguments[0], fn, params, locals_, transfers, count,
                depth + 1,
            )
        raise _Unsupported("unsupported_expression", _span(node))

    def _direct_import_call(
        self,
        call: Any,
        arguments: list[Any],
        fn: Any,
        params: list[Any],
        locals_: dict[Any, Any],
        transfers: list[Any],
        count: int,
        depth: int,
        receiver: Any = None,
    ) -> frozenset[int]:
        # The callee lives in a resolved imported unit; its body is
        # opaque here. The result may depend on every argument — an
        # over-approximation — and the recorded target is the imported
        # unit's own binding identity, so a regenerated report for it
        # still flags this summary via `stale_dependents`. Package-level
        # state is not modelled. A method call also depends on its
        # receiver expression, evaluated before the arguments. A
        # composite imported var receiver (`lib.VS.PM(x)` on a struct
        # var) reads external state like the member itself — a plain
        # member read would reject it as unrepresentable, but as a
        # receiver it is dep-free and still records the imported
        # transfer.
        receiver_deps = frozenset()
        if receiver is not None:
            receiver_member = self._imported_member_operand(receiver)
            handled = (
                receiver_member is not None
                and receiver_member.kind == "var"
                and self._composite_var_read(
                    receiver, receiver_member, transfers
                )
            )
            if not handled:
                # `lib.VSS[i].PF()` — a composite element of an
                # imported container as the receiver reads external
                # state like the container, dep-free apart from the
                # indexes.
                index_deps = self._index_receiver_read(
                    receiver, fn, params, locals_, transfers, count,
                    depth,
                )
                if index_deps is not None:
                    receiver_deps = index_deps
                else:
                    receiver_deps = self.expression(
                        receiver, fn, params, locals_, transfers, count,
                        depth + 1,
                    )
        # `t.W.Get()` — a nested-selector receiver reads dep-free like
        # any field read, but a `t.W.f = v` write folded the value's
        # deps into the chain's root binding and a method call on the
        # chain can observe them, so the root binding's deps join the
        # receiver's.
        if receiver is not None:
            root_ref = self._bound_receiver_root(receiver, locals_, params)
            if root_ref is not None:
                binding_id = root_ref.binding_id
                if binding_id in locals_:
                    receiver_deps |= locals_[binding_id]
                elif binding_id in params:
                    receiver_deps |= frozenset({params[binding_id]})
        # A method expression `lib.T.M(recv, args)` carries the
        # receiver as its leading argument — a composite imported var
        # in that slot reads external state like `lib.VS.PF()` does:
        # dep-free with the member's transfer on record.
        actual = []
        for i, arg in enumerate(arguments):
            arg_member = (
                self._imported_member_operand(arg)
                if i == 0 and getattr(call, "method_expr", False)
                else None
            )
            if (
                arg_member is not None
                and arg_member.kind == "var"
                and self._composite_var_read(arg, arg_member, transfers)
            ):
                actual.append(frozenset())
                continue
            arg_index_deps = (
                self._index_receiver_read(
                    arg, fn, params, locals_, transfers, count, depth
                )
                if i == 0 and getattr(call, "method_expr", False)
                else None
            )
            if arg_index_deps is not None:
                actual.append(arg_index_deps)
                continue
            actual.append(
                self.expression(
                    arg, fn, params, locals_, transfers, count,
                    depth + 1,
                )
            )
        actual = tuple(actual)
        result = (
            frozenset().union(*actual) if actual else frozenset()
        ) | receiver_deps
        transfers.append(
            CallTransfer(call.span, call.target, actual, result, imported=True)
        )
        # `&x` hands the callee an alias of a local/param binding — an
        # opaque callee may write through it, so afterwards the binding
        # conservatively depends on every argument (its own old deps are
        # already inside `result` because `&x` contributed them).
        self._store_call_writes(arguments, result, locals_, params)
        # The callee's declared named/alias signature types are pinned
        # the same way a member read's declared type is: redeclaring one
        # flags this summary even when the callee's own identity is
        # unchanged.
        member = self.members.get(call.target)
        if member is not None:
            self.pinned.update(member.signature_type_ids)
        # An instantiated callee's named/alias type arguments pin their
        # substituted identities at this call site — `lib.G[lib.T](x)`
        # goes stale when `lib.T` is redeclared even though the member
        # record's declared signature names only the type parameter.
        self.pinned.update(getattr(call, "type_arg_type_ids", ()))
        return result

    def _store_call_writes(
        self,
        arguments: list[Any],
        stored: frozenset[int],
        locals_: dict[Any, Any],
        params: dict[Any, int],
    ) -> None:
        # `&x` hands the callee an alias of a local/param binding — an
        # effectful callee may write through it, so afterwards the
        # binding conservatively depends on `stored` (every argument's
        # deps at an opaque call; the same approximation at a local
        # callee with unknown effects).
        for arg_node in arguments:
            # `&` is an anonymous child — `_children` only yields the
            # named operand, so check the raw first child.
            if (
                arg_node.type == "unary_expression"
                and arg_node.children
                and arg_node.children[0].type == "&"
            ):
                (operand,) = _children(arg_node)
                ref = (
                    self.references.get(self.node_key(operand))
                    if operand.type == "identifier"
                    else None
                )
                if ref is not None and (
                    ref.binding_id in locals_ or ref.binding_id in params
                ):
                    base = (
                        locals_.get(ref.binding_id)
                        if ref.binding_id in locals_
                        else frozenset({params[ref.binding_id]})
                    )
                    locals_[ref.binding_id] = base | stored


def summarize_go(source: str, snapshot: GoTypeSnapshot) -> GoSummarySet:
    """Compose conservative dependencies only; never infer equality or safety.

    A nonempty set can overapproximate dependence (e.g. x*0 still includes x).
    Empty means parameter-independent in this fragment, not a known constant.
    None means unavailable, never a parameter-independent or effect-free result.
    """
    raw, key = _context(source, snapshot)
    builder = _Builder(
        {0: raw}, snapshot, key, lambda bid: snapshot.cfg_for_function(source, bid)
    )
    if len(snapshot.functions) > MAX_FUNCTIONS:
        results = tuple(
            builder.result(f, gaps=(SummaryGap("analysis_limit"),))
            for f in snapshot.functions
        )
    else:
        results = tuple(
            builder.summarize(f.binding_id)
            for f in sorted(snapshot.functions, key=lambda f: f.binding_id)
        )
    return GoSummarySet(key, results, snapshot.target_arch)


def summarize_go_package(
    sources: "dict[str, str] | list[str]", snapshot: GoPackageSnapshot
) -> GoSummarySet:
    """The multi-file package variant of `summarize_go`.

    One package unit — every function shares the package scope, calls
    across file boundaries resolve to `direct_local`, and every binding
    identity carries its declaring file's digest, so replacing one file
    only churns that file's identities (`stale_dependents` still
    applies). `sources` maps each declared file name to its contents
    (or lists them in declaration order); digests re-validate.

    Calls into host-resolved imported units record `direct_import`
    transfers: the callee body is opaque, so the result is treated as
    potentially depending on every argument — an over-approximation;
    package-level state is not modelled. The target is the imported
    unit's own binding identity, so regenerating that unit's report
    churns it and `stale_dependents` still flags dependents. A summary
    recording such a transfer reports `effects` as `unknown` — the
    imported callee's side effects are outside the fragment. Only
    imported calls whose results are all scalar are classified
    `direct_import`; composite results keep `external_or_bodyless` and
    fail closed. A multi-valued imported call declares its arity on the
    record and unpacks in a tuple binding (`a, b := lib.F(x)`, plain
    assignment, or `var` spec): each result carries the same
    over-approximated dependency set, so a single evaluation stores to
    every name. Spread arguments (`lib.F(lib.G(x))`) need no arity —
    the inner call's unioned deps already cover the outer result.

    Reports may declare the imported objects the unit referenced
    (`imported_members`). A package-qualified read of a scalar
    constant (`lib.K`) is admitted — constants carry no dependencies,
    like local constants. A scalar imported `var` read (`lib.V`)
    records an imported transfer against the member identity —
    external state like an imported call, so `effects` reports
    `unknown`; non-scalar members and imported functions used as
    values stay closed. The unit's own package-level `var`s admit
    the same way: reads and writes (`G`, `G = v`, `G += v`,
    `G++`/`G--`) record imported transfers against the var's binding
    identity — in `known`, so `stale_dependents` flags on
    redeclaration. Reports without the
    section load unchanged; the member record only widens what was
    already unmodelled.
    """
    raws, key = _package_context(snapshot, sources)
    builder = _Builder(
        dict(enumerate(raws)),
        snapshot,
        key,
        lambda bid: snapshot.cfg_for_function(sources, bid),
    )
    if len(snapshot.functions) > MAX_FUNCTIONS:
        results = tuple(
            builder.result(f, gaps=(SummaryGap("analysis_limit"),))
            for f in snapshot.functions
        )
    else:
        results = tuple(
            builder.summarize(f.binding_id)
            for f in sorted(snapshot.functions, key=lambda f: f.binding_id)
        )
    return GoSummarySet(key, results, snapshot.target_arch)
