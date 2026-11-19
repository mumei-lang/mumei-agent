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

import ast
import hashlib
import json
import sys
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
# The `statement`/`expression` wrappers that attribute per-statement
# reads cost one extra Python frame per analyzed level; deep
# expression nesting plus callee `summarize` recursion was already
# near the interpreter's default ceiling, so the analyzer raises it
# to keep the same logical `MAX_DEPTH` budget reachable.
sys.setrecursionlimit(max(sys.getrecursionlimit(), 16384))
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
_INDEX_LITERALS = frozenset(
    {
        "int_literal",
        "float_literal",
        "imaginary_literal",
        "rune_literal",
        "interpreted_string_literal",
        "raw_string_literal",
    }
)


def _go_int_literal(text: str) -> int | None:
    """Value of a Go integer literal — decimal, `0x`/`0X` hex,
    `0o`/`0O` and leading-zero octal, `0b`/`0B` binary, with `_`
    digit separators. None when the text does not parse."""
    t = text.replace("_", "")
    try:
        if t[:2].lower() in {"0x", "0o", "0b"}:
            return int(t, 0)
        if len(t) > 1 and t[0] == "0":
            return int(t, 8)
        return int(t, 10)
    except ValueError:
        return None


def _go_rune_literal(text: str) -> int | None:
    """Ordinal of the character a Go rune literal names — `'a'`,
    `'\\x41'`, `'\\u1234'`, `'\\101'`, `'\\n'`. None when it does not
    parse."""
    inner = text[1:-1] if len(text) >= 2 else text
    if len(inner) == 1 and inner != "\\":
        return ord(inner)
    if not inner.startswith("\\"):
        return None
    esc = inner[1:]
    single = {
        "a": 7, "b": 8, "f": 12, "n": 10, "r": 13, "t": 9,
        "v": 11, "\\": 92, "'": 39, '"': 34, "0": 0,
    }
    if esc in single:
        return single[esc]
    try:
        if esc[:1] == "x" and len(esc) == 3:
            return int(esc[1:], 16)
        if esc[:1] == "u" and len(esc) == 5:
            return int(esc[1:], 16)
        if esc[:1] == "U" and len(esc) == 9:
            return int(esc[1:], 16)
        if esc and esc[0].isdigit():
            return int(esc, 8)
    except ValueError:
        return None
    return None


def _go_interpreted_string(text: str) -> str:
    """Content of a Go interpreted string literal with escapes
    resolved; the unquoted raw text when parsing fails."""
    try:
        value = ast.literal_eval(text)
        if isinstance(value, str):
            return value
    except (SyntaxError, ValueError):
        pass
    return text[1:-1] if len(text) >= 2 else text


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
    # `folded_targets` records the callee identities a
    # `--summary-aware-calls` fold embedded into `result` — the declared
    # callee's own `call_targets` transitively through the manifest —
    # so `stale_dependents` flags this summary when any folded dep
    # churns, not only the directly named callee. Emitted only when
    # non-empty; reports lacking the field load unchanged.
    folded_targets: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        result = {
            "span": _span_dict(self.span),
            "target": self.target,
            "arguments": [sorted(argument) for argument in self.arguments],
            "result": sorted(self.result),
        }
        if self.imported:
            result["imported"] = True
        if self.folded_targets:
            result["folded_targets"] = sorted(self.folded_targets)
        return result

    @classmethod
    def from_dict(cls, value: Any) -> "CallTransfer":
        v = _manifest_record(
            value,
            ("span", "target", "arguments", "result"),
            ("imported", "folded_targets"),
        )
        span = _span_from_dict(v["span"])
        _require_restore(span is not None)
        arguments = _list(v["arguments"])
        _require_restore(len(arguments) <= MAX_MANIFEST_MEMBERS)
        folded = ()
        if "folded_targets" in v:
            folded_list = _list(v["folded_targets"])
            _require_restore(len(folded_list) <= MAX_MANIFEST_MEMBERS)
            folded = tuple(_string(t) for t in folded_list)
        return cls(
            span,
            _string(v["target"]),
            tuple(_deps_from_list(a) for a in arguments),
            _deps_from_list(v["result"]),
            _boolean(v["imported"]) if "imported" in v else False,
            folded,
        )


@dataclass(frozen=True)
class StatementRead:
    """The parameter ordinals one statement's evaluation read.

    A read inside a nested block attributes to every enclosing
    statement, like dep flow itself: `if c { y = x }` records `x`
    against both the assignment and the `if`. Descriptive only —
    like `calls`, it never feeds `for_function`/`stale_dependents`.
    """

    span: ByteSpan | FileSpan
    deps: frozenset[int]

    def to_dict(self) -> dict:
        return {
            "span": _span_dict(self.span),
            "deps": sorted(self.deps),
        }

    @classmethod
    def from_dict(cls, value: Any) -> "StatementRead":
        v = _manifest_record(value, ("span", "deps"), ())
        span = _span_from_dict(v["span"])
        _require_restore(span is not None)
        return cls(span, _deps_from_list(v["deps"]))


@dataclass(frozen=True)
class _AnonymousPointee:
    """The pointee record a bound `*struct{...}` supplies — the
    anonymous struct names no `type` member, so its slot in a
    resolved pointer chain carries the synthetic `<binding>/pointee`
    identity and the pointee fact itself for classification."""

    id: str
    type: Any


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
    # Per-statement read attribution: `(span, parameter ordinals)` for
    # each walked statement, nested reads included. Emitted only on
    # available summaries — a gapped walk would misattribute — and
    # never authorizes anything (descriptive like `calls`).
    statement_reads: tuple[StatementRead, ...] = ()

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
            target
            for call in self.calls
            for target in (call.target, *call.folded_targets)
            if not target.endswith("/pointee")
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
        if self.statement_reads:
            result["statement_reads"] = [
                read.to_dict() for read in self.statement_reads
            ]
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
            (
                "result_type",
                "return_dependencies",
                "pinned",
                "statement_reads",
            ),
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
        restored_reads = (
            tuple(StatementRead.from_dict(r) for r in _list(v["statement_reads"]))
            if "statement_reads" in v
            else ()
        )
        _require_restore(
            len(restored_reads) <= MAX_MANIFEST_MEMBERS
            and all(
                d < len(parameters)
                for r in restored_reads
                for d in r.deps
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
            restored_reads,
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


def _declared_context_key(key: str, declared: "GoSummarySet | None") -> str:
    """Fold the callee manifest's canonical bytes into the context key.

    Under `--summary-aware-calls` the declared manifest is a
    derivation input like the source snapshot: without it in the
    key, a changed callee manifest leaves the strict whole-context
    gate accepting records derived from different declared deps.
    """
    if declared is None:
        return key
    payload = json.dumps(
        [key, declared.to_dict()], sort_keys=True
    ).encode()
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class GoSummarySet:
    context_key: str
    functions: tuple[FunctionSummary, ...]
    # The gc target the set was derived for — `int`/`uintptr` widths are
    # arch-dependent while binding identities are not, so a manifest
    # must declare it for a reuse route to refuse a mismatched unit.
    target_arch: str | None = None
    profile: str = PROFILE
    # `--summary-aware-calls` reporting: present only on manifests the
    # route derived with a declared callee manifest — advisory counts
    # (`summary_modeled_calls` folded, `opaque_calls` left opaque,
    # `summary_unmatched` manifest entries never referenced), never a
    # verdict or a gate.
    call_modeling: dict | None = None

    def for_function(
        self,
        source: str,
        snapshot: GoTypeSnapshot,
        binding_id: str,
        declared: "GoSummarySet | None" = None,
    ) -> FunctionSummary:
        """Reject reuse after any source, target, compiler or report change."""
        if (
            _declared_context_key(
                _context(source, snapshot)[1], declared
            )
            != self.context_key
        ):
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
        declared: "GoSummarySet | None" = None,
    ) -> FunctionSummary:
        """The package-unit variant of `for_function` — same staleness rule."""
        if (
            _declared_context_key(
                _package_context(snapshot, sources)[1], declared
            )
            != self.context_key
        ):
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
        if self.call_modeling is not None:
            result["call_modeling"] = self.call_modeling
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
            ("target_arch", "call_modeling"),
        )
        _require_restore(v["schema_version"] == PROFILE)
        functions = _list(v["functions"])
        _require_restore(len(functions) <= MAX_MANIFEST_MEMBERS)
        restored = tuple(FunctionSummary.from_dict(f) for f in functions)
        _require_restore(len({f.binding_id for f in restored}) == len(restored))
        target_arch = (
            _string(v["target_arch"]) if "target_arch" in v else None
        )
        call_modeling = None
        if "call_modeling" in v:
            m = _manifest_record(
                v["call_modeling"],
                ("summary_modeled_calls", "opaque_calls", "summary_unmatched"),
            )
            for key_ in (
                "summary_modeled_calls",
                "opaque_calls",
                "summary_unmatched",
            ):
                _require_restore(
                    isinstance(m[key_], int) and m[key_] >= 0
                )
            call_modeling = {
                k: m[k]
                for k in (
                    "summary_modeled_calls",
                    "opaque_calls",
                    "summary_unmatched",
                )
            }
        return cls(
            _string(v["context_key"]),
            restored,
            target_arch,
            call_modeling=call_modeling,
        )


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
        declared: "dict[tuple[str, int], FunctionSummary] | None" = None,
    ):
        self.snapshot, self.key, self.cfg_fn = snapshot, key, cfg_fn
        # Declared callee summaries (`--summary-aware-calls`): folded
        # into `direct_import` calls whose target binding identity the
        # manifest covers — trusted as declared, like every declared
        # input. Keyed by (file digest, declaration start), which a
        # manifest mints identically under either unit shape, so no
        # context key gates and a single-file callee manifest folds
        # into package-minted call targets too.
        self.declared = declared or {}
        self._declared_seen: set[str] = set()
        self._modeled_spans: set[tuple[int, int, int]] = set()
        self._opaque_spans: set[tuple[int, int, int]] = set()
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
        # Bound closures (`h := func()...`) whose literal references an
        # enclosing pointer-typed binding: invoking one reads caller
        # memory like a `*p` read, so `h()` records an imported
        # transfer (effects unknown) and unions `indirect_writes`.
        self.pointee_closures: set[str] = set()
        # Bound name → the enclosing-scope binding ids its literal
        # captured. `h()` resolves each captured id's CURRENT deps
        # (params or locals at the call site) — freezing the dep set
        # at bind time goes stale when a captured local is reassigned
        # between the literal and the call (`p := &a; h := func(){*p};
        # p = &b; h()` reads `b`, not `a`).
        self.closure_captures: dict[str, frozenset[str]] = {}
        # Bound method values — `f := s.M` records `(method binding,
        # receiver binding)` under `f`'s id so a later `f(args)`
        # resolves through the method's summary like `s.M(args)` does.
        self.bound_method_values: dict[
            str, tuple[str, str | None, str | None]
        ] = {}
        # A method value COPIES the receiver at bind time — freeze
        # the receiver's dep set then, so a `s = …` reseat before
        # `f(args)` still resolves the ORIGINAL receiver's deps.
        self.bound_method_receiver_deps: dict[
            str, frozenset[int]
        ] = {}
        # Bound name → the enclosing-scope bindings its literal's
        # body WRITES (`x = e`, `s.V = e`, `p[i] = e`). `h()` folds
        # the write's value deps into each target's dep set — the
        # literal runs at the call, so its stores sequence there.
        self.closure_writes: dict[str, frozenset[str]] = {}
        # Bound names whose literal writes through `*p` — the store
        # lands on caller memory the binding cannot name, so `h()`
        # folds write deps into every escaped binding like a `*p = e`
        # statement does.
        self.closure_star_writes: set[str] = set()
        # Bound names whose literal body contains a call: the inner
        # call's effects are unplaceable at bind time, so `h()` is an
        # opaque effectful callee — args + captured deps into escaped
        # bindings and indirect_writes, imported transfer recorded.
        self.closure_inner_calls: set[str] = set()
        # Function-name aliases — `h := G` / `h = G` / `var h = G`
        # binds the name to a DECLARED function: `h(x)` resolves
        # through G's own summary exactly like a `direct_local`
        # call. The map holds a target only while every path to the
        # call binds that one function — a literal rebind, a
        # maybe-skipped rebind to a different target, or a store
        # whose RHS is not a known function clears it and the call
        # falls back to the opaque external callee model.
        self.func_aliases: dict[str, str] = {}
        # Bound names whose call must fold BOTH a literal's capture/
        # write records AND a non-literal callee a maybe-skipped rebind
        # left live on the untaken path (`f := cb; if b { f =
        # func()... }` — either the parameter callback or the literal
        # may run). The name KEEPS its closure records so the call
        # resolves the literal alternatives' captures and write
        # targets with CURRENT deps, and the marker makes the call
        # apply the external model (name's own dep set, escaped
        # bindings, indirect writes) for everything else. A fresh
        # unconditional bind clears the marker.
        self.opaque_callees: set[str] = set()
        # Function names read in a call's argument list — `H(G, x)`
        # — pending fold until the call's own deps are known: the
        # callee may invoke G, so the possible invocation records a
        # transfer on G's identity and, when G's own effects are
        # unbounded, the call's deps broadcast into
        # `indirect_writes` like any other opaque write. Keyed by
        # the enclosing call node; drained by `expression` once the
        # call finishes evaluating every argument.
        self._func_arg_invocations: dict[
            tuple[str, int, int], list[tuple[Any, str]]
        ] = {}
        # Each call's evaluated-argument deps, accumulated as every
        # argument returns through `expression` — the set a passed
        # function value may be invoked WITH. Drained beside
        # `_func_arg_invocations` when the call finishes.
        self._call_arg_deps: dict[
            tuple[str, int, int], frozenset[int]
        ] = {}
        # Channel aliases — `ch2 := ch` / `var ch2 = ch` / `ch2 = x`
        # copies one queue's name, not its contents, so sends through
        # the alias must land in the SOURCE binding's dep set. The
        # alias maps the new name to the channel binding it copied;
        # `_chan_binding` resolves the chain before classifying the
        # operand as local queue or shared parameter.
        self.chan_aliases: dict[str, str] = {}
        # Locals bound to a callee-produced queue (`ch := g()` where
        # `g` declares a scalar `chan` result) — ops on them follow
        # the parameter's external model (sends broadcast into
        # `indirect_writes`, reads union it) rather than the
        # conflated-set model a `make(chan)` local uses.
        self.external_chan_locals: set[str] = set()
        # Bindings that died at a scope join — a branch-local `t`
        # captured by a stored literal (`fs[0] = func() { return t }`)
        # still names the value its last write gave it. `_join`
        # freezes each dying binding's deps here so a call after the
        # merge re-resolves the captured name's last value instead of
        # losing the dep.
        self._dead_local_deps: dict[str, frozenset[int]] = {}
        # Func-element containers sharing one backing — `fs2 := fs`
        # copies a slice/map's name, not its elements, so an element
        # store through either name reaches the other. Each binding
        # maps to the names it shares with; a non-append reseat
        # (`fs = mk()`, `fs = []func(){…}`, `fs = nil`) hands the old
        # element records to the aliases and detaches, while
        # `fs = append(fs, …)` keeps the share — the grown slice may
        # reuse the same array.
        self._func_elem_groups: dict[str, set[str]] = {}
        # Per-name backing identity: a set of opaque tokens, one
        # per array instance the name may currently point at. A
        # copy unions the operand's tokens onto the target; a
        # definite reseat replaces them with a fresh token. Token
        # sets (not pairwise edges) decide "same backing" — a
        # conditional reseat leaves a name holding EITHER backing
        # and a union of tokens keeps those alternatives separate,
        # where merged share edges would fuse the old and new
        # backings into one class (`c := b`; if-`b = a`; `d := a`
        # — `c` and `d` never share).
        self._func_elem_tokens: dict[str, frozenset[str]] = {}
        self._func_elem_token_seq = 0
        # `fm := [][]func{fs}` — only the slot initialized from
        # `fs` aliases its backing, so the donor set is keyed by
        # the composite element's position (or literal map key):
        # binding_id -> slot key -> donor bindings.
        self._func_elem_inner_donors: dict[str, dict[str, set[str]]] = {}
        self._func_elem_surrogate_seq = 0
        # For an anonymous-`struct{...}` binding whose fields do not
        # follow its own name span, the span that DOES precede them:
        # `cp := st` copies st's (anonymous) type, so cp's fields are
        # declared in st's literal — after st's anchor — and
        # `var a, b struct{...}` declares the literal after the LAST
        # name, so a's fields follow b's span, not a's.
        self.anon_struct_anchor: dict[str, Any] = {}
        # binding id -> the DIRECT field names of the anonymous
        # struct literal its field window anchors at. Identical
        # literals unify in the type checker, so `cp.V` may resolve
        # to a different literal's binding — a name match against
        # THIS set (not every scope-less binding in the window,
        # which would admit a promoted name colliding with a
        # nested literal's inner field) keeps that sound.
        self.anon_struct_field_names: dict[str, frozenset[str]] = {}
        # Whether the statement currently running may not execute —
        # a closure rebind inside a branch unions its captures like
        # `_store` unions the binding's deps. `_conditional` covers
        # post-exit skips; `_may_skip` covers branch/loop scope
        # copies, whose writes only join back by union.
        self._conditional = False
        self._may_skip = 0
        # Per-statement read attribution: `statement` pushes one list
        # per walked statement and `expression` appends every dep set
        # it returns to all open frames, so a nested read lands on
        # every enclosing statement. `_stmt_reads` merges the unions
        # by span — a loop's fixed-point re-passes re-record the same
        # spans idempotently.
        self._read_stack: list[list[frozenset[int]]] = []
        self._stmt_reads: dict[tuple[int, int, int], list] = {}
        # Pointer provenance per binding — what the pointer itself
        # depends on, tracked separately from `locals_`: a
        # bound-pointer store (`p.V = x`) folds the stored value's
        # deps into `locals_[p]` as pointee contents, but the
        # pointer's own deps never change. A later write through `p`
        # reads the pointer, not the folded contents, so the two sets
        # must not conflate. Recorded at every plain store and
        # declaration; `_join` scopes union back via `_join_ptr`.
        self._ptr_deps: dict[str, frozenset[int]] = {}
        # Which queues a `chan` field member may currently hold —
        # `p.C = ch` unions `ch`'s token into the member's may-set
        # (never replaces: a conditional store leaves the old queue
        # a candidate). Reads on `p.C` union every token's queue
        # deps — an over-approx like the escaped-binding fold.
        self.field_chan_queues: dict[str, frozenset[str]] = {}
        # Argument deps of deferred calls whose callee may write —
        # a deferred store lands AFTER the return expressions
        # evaluate, so it can still change a named result: every
        # later `return` unions this set.
        self._defer_result_deps: frozenset[int] = frozenset()
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

    def _embed_name_compatible(self, field: Any) -> bool:
        """A pre-`embedded` report leaves the field unmarked, but the
        declaration form is still visible in source: a name followed
        by a type (`R *Q`, `Q Q`) or another name (`A, B *Q`) is
        definitely NAMED — an embedded field is a bare identifier,
        so only a `\\n` / `;` / `}` (or EOF, possibly after a
        tag or a comment) may follow it. Comparing
        the field name to the resolved type's name fails for
        aliases (`type A = *Q` embeds as `A`, not `Q`), so the
        source text after the field's own span decides."""
        span = getattr(field, "span", None)
        if span is None:
            return True
        raw = self.raws.get(getattr(span, "file", 0) or 0)
        if raw is None:
            return True
        i, n = span.end, len(raw)
        while True:
            while i < n and raw[i:i + 1] in (b" ", b"\t", b"\r"):
                i += 1
            if raw[i:i + 2] == b"//":
                j = raw.find(b"\n", i)
                i = n if j < 0 else j + 1
                continue
            if raw[i:i + 2] == b"/*":
                j = raw.find(b"*/", i + 2)
                i = n if j < 0 else j + 2
                continue
            if raw[i:i + 1] == b"`":
                # A struct tag can decorate an embedded field too
                # (`*Q `json:"q"``) — skip it and keep checking.
                j = raw.find(b"`", i + 1)
                i = n if j < 0 else j + 1
                continue
            break
        if i >= n:
            return True
        return raw[i:i + 1] in (b"\n", b";", b"}")

    def _promotion_path(
        self,
        fields: tuple[Any, ...],
        ident: Any,
        seen: frozenset[str],
    ) -> tuple[str, Any | None] | None:
        """`ident`'s promotion path through `fields`, if found.

        Selectors promote only through EMBEDDED (anonymous) fields
        and resolve at the shallowest depth — `type S struct{ R Q;
        *Q }` reaches `P` via `*Q` alone (the named `R Q` never
        carries a promotion), and `type S struct{ R; Q }` picks
        `Q` over the deeper `R.*Q`. A breadth-first walk over
        embedded fields matches both rules; a same-depth
        ambiguity does not compile, so the first hit at a level
        is the program's real path.

        Returns `("ptr", ftype)` with the shallowest pointer-typed
        embedded field's type fact when the path crosses one,
        `("value", None)` when `ident` is reached through value
        fields only, `("ptr", f.type)` when an embedded field's
        type is unenumerable (imported or anonymous) so `ident`
        may hide behind an invisible pointer, or None when no
        embedded field's type declares `ident` (its declaring
        type is unreachable from the container's field list)."""
        # (embedded field, the path's first pointer-typed field)
        frontier: list[tuple[Any, Any | None]] = [
            (f, ftype if ftype.kind == "pointer" else None)
            for f in fields
            if getattr(f, "embedded", None) is not False
            and (getattr(f, "embedded", None) is True
                 or self._embed_name_compatible(f))
            and (ftype := getattr(f, "type", None)) is not None
        ]
        while frontier:
            nxt: list[tuple[Any, Any | None]] = []
            unenumerable: Any | None = None
            found_value = False
            for f, ptr_field in frontier:
                ftype = f.type
                pointee = (
                    ftype.elem if ftype.kind == "pointer" else ftype
                )
                tid = getattr(pointee, "type_id", "")
                tb = self._pointee_type(tid) if tid else None
                if tb is None or getattr(tb, "span", None) is None:
                    # `type S struct{ lib.Q }` — an imported or
                    # otherwise unenumerable embedded type: `ident`
                    # may sit inside it behind a pointer the
                    # report cannot see.
                    if unenumerable is None:
                        unenumerable = f
                    continue
                inner = self._struct_fields(tb)
                if ident.id in {x.id for x in inner}:
                    # Keep scanning the level: a pointer-typed
                    # sibling may carry the real promotion (a
                    # pre-`embedded` report cannot tell `R Q` from
                    # `*Q`), so a same-depth pointer crossing wins
                    # over this value match.
                    if ptr_field is not None:
                        return ("ptr", ptr_field)
                    found_value = True
                    continue
                if tb.id in seen:
                    continue
                seen = seen | {tb.id}
                nxt.extend(
                    (
                        g,
                        ptr_field
                        if ptr_field is not None
                        else (
                            gtype if gtype.kind == "pointer" else None
                        ),
                    )
                    for g in inner
                    if getattr(g, "embedded", None) is not False
                    and (getattr(g, "embedded", None) is True
                         or self._embed_name_compatible(g))
                    and (gtype := getattr(g, "type", None)) is not None
                )
            if found_value:
                # A known value read beats an unknown path: when
                # `lib.X` could *also* declare `ident`, the
                # compiler would have rejected the promotion as
                # ambiguous, so the unenumerable type cannot carry
                # this read in a valid program.
                return ("value", None)
            if unenumerable is not None:
                return ("ptr", unenumerable.type)
            frontier = nxt
        return None

    def _promoted_field_pointer(
        self,
        container_type: Any | None,
        ident: Any,
        call: Any | None = None,
    ) -> Any | None:
        """The embedded `*Q` a promoted field read crosses, if any.

        `g(q).P` on `type S struct{ *Q; ... }` resolves `P` to its
        own declaring type `Q` — the syntactic chain names no
        pointer, but the read dereferences the embedded one. `P`
        is a DIRECT field when it is one of the container's
        declared fields; otherwise the read promotes, and the
        crossing is the pointer-typed field on `P`'s promotion
        path (an unrelated `R *R` sibling does not count — only
        the field whose type actually declares `P`). Returns None
        for direct fields and for promotions through value
        embedding (`type S struct{ Q }` — no deref). A container
        whose fields cannot be enumerated (an imported type, or
        an anonymous literal in a callee with no resolvable
        signature region) is treated as a crossing — the promoted
        read may dereference an embed the report cannot see."""
        if container_type is None or container_type.kind != "struct":
            return None
        type_id = container_type.type_id
        if type_id:
            if type_id not in self.bindings:
                # An imported type member — the field list is not
                # enumerable, so `ident` may be promoted through an
                # embedded pointer the report does not carry.
                return container_type
            direct_fields = self._struct_fields(
                self.bindings[type_id]
            )
            if ident.id in {f.id for f in direct_fields}:
                return None
        else:
            # An anonymous `struct{...}` result — its direct fields
            # are the scope-less bindings inside the callee's
            # signature region (after the function's name span,
            # before its body). A promoted field binds inside its
            # own declaring type, outside that region.
            target = (
                self.functions.get(call.target)
                if call is not None
                else None
            )
            binding = (
                self.bindings.get(target.binding_id)
                if target is not None
                else None
            )
            name_span = getattr(binding, "span", None)
            body_span = getattr(target, "body", None)
            if name_span is None or body_span is None:
                # An imported or bodiless callee — the literal's
                # fields cannot be enumerated.
                return container_type
            rfile = (
                name_span.file if isinstance(name_span, FileSpan) else 0
            )
            direct_fields = tuple(
                b
                for b in self.bindings.values()
                if b.kind == "variable"
                and b.scope is None
                and isinstance(b.span, FileSpan)
                and b.span.file == rfile
                and name_span.end < b.span.start < body_span.start
            )
            ispan = getattr(ident, "span", None)
            if (
                isinstance(ispan, FileSpan)
                and ispan.file == rfile
                and name_span.end < ispan.start < body_span.start
            ):
                return None
        path = self._promotion_path(direct_fields, ident, frozenset())
        if path is not None:
            return path[1] if path[0] == "ptr" else None
        # `ident` is not direct but no field's type declares it —
        # the declaring type sits deeper than the model reaches:
        # any pointer-typed direct field may carry the crossing.
        for f in direct_fields:
            ftype = getattr(f, "type", None)
            if ftype is not None and ftype.kind == "pointer":
                return ftype
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
        """A package-local composite value — `st := P{...}` or
        `st := struct{...}{...}`.

        Named composite declarations (`struct`/`interface`/`chan`/
        `func` shapes) carry `type.kind == "unsupported"` plus a
        `type_id` naming the `type` declaration, and anonymous
        `struct{...}` values carry `type.kind == "struct"` with no
        `type_id`; other unnamed composites (`[]T`, `map`, `string`)
        keep their own kinds and stay closed. The binding's single
        dep set conflates all fields — a sound over-approximation in
        both directions. The named type's identity pins on every
        admit so `stale_dependents` flags the summary when the type
        is redeclared; an anonymous struct has no identity to
        redeclare, so nothing pins.
        """
        if (
            binding is None
            or binding.type is None
            or binding.type.kind not in {"unsupported", "struct"}
        ):
            return False
        if not binding.type.type_id:
            # Anonymous `struct{...}` value — `kind` alone carries the
            # shape, and there is no `type` identity to pin or
            # redeclare. Other anonymous composites keep their own
            # kinds (`slice`/`map`/...) and already failed above.
            return binding.type.kind == "struct"
        composite = self._pointee_type(binding.type.type_id) is not None
        if composite:
            self.pinned.add(binding.type.type_id)
        return composite

    def _elem_call_conversion(self, node: Any) -> bool:
        """`fs[i](x)` parses as a `type_conversion_expression` — the
        recorded call still classifies it as an element call
        (`call.kind == "indirect_or_selector"`); a real `T(x)`
        conversion records `call.kind == "conversion"` and keeps
        its operand in value position."""
        if node is None or node.type != "type_conversion_expression":
            return False
        call = self.calls.get(self.node_key(node))
        return call is not None and call.kind == "indirect_or_selector"

    def _func_elem_collection(self, fact: Any) -> bool:
        """A `[]func`/`[N]func`/`map[K]func` container — a collection
        whose elements are function values. It binds like a composite
        local: one conflated dep set carries every element's
        captured state, and `fs[k]()` then calls opaque on the
        container's slot like an imported member's element does.
        A keyed map slot is as unknowable as a slice index, so the
        keyed `fm["k"]()` resolves through the same slot. A named
        container type (`type FS []func`, `type FM map[K]func`)
        pins its declared identities on admit — the caller's
        element-call contract changes with a redeclaration like a
        named composite's does."""
        collection = (
            fact is not None
            and fact.kind in {"slice", "array", "map"}
            and getattr(fact, "elem", None) is not None
            and fact.elem.kind == "function"
        )
        if collection:
            self._pin_fact_identities(fact)
        return collection

    def _func_elem_nested_collection(self, fact: Any) -> bool:
        """A collection of func-element collections —
        `map[K][]func`, `[][]func`, `[N]map[K]func`. One extra
        nesting level only: `fm[k]` yields a container whose slots
        conflate under the root binding like `fm[k]`'s own elements
        do. Deeper nesting stays closed."""
        collection = (
            fact is not None
            and fact.kind in {"slice", "array", "map"}
            and getattr(fact, "elem", None) is not None
            and self._func_elem_collection(fact.elem)
        )
        if collection:
            # Pin the WHOLE type tree like the single-level admit —
            # the outer named container and outer map key otherwise
            # escape `stale_dependents` when their declarations change.
            self._pin_fact_identities(fact)
        return collection

    def _func_elem_nested_operand(
        self, operand: Any
    ) -> tuple[str, Any, Any | None] | None:
        """`fm[k]` as the operand of a further index — the inner
        operand must name a bound collection of collections.
        Returns (root binding id, inner identifier node, inner
        index node) for `fm[k]`, or None otherwise."""
        if operand is None or operand.type != "index_expression":
            return None
        inner = operand.child_by_field_name("operand")
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
        if inner is None or inner.type != "identifier":
            return None
        ref = self.references.get(self.node_key(inner))
        if ref is None or not ref.binding_id:
            return None
        bound = self.bindings.get(ref.binding_id)
        if bound is None or not self._func_elem_nested_collection(
            bound.type
        ):
            return None
        return (
            ref.binding_id,
            inner,
            operand.child_by_field_name("index"),
        )

    def _is_func_elem_composite(self, rhs_node: Any, binding_id: str) -> bool:
        """`fs := []func(){…}` — a composite literal binding to a
        func-element container. Its element literals record captures
        under the container's name during RHS evaluation, so the
        generic func-value record cleanup must not erase them."""
        bound = self.bindings.get(binding_id)
        return (
            rhs_node is not None
            and rhs_node.type == "composite_literal"
            and bound is not None
            and (
                self._func_elem_collection(bound.type)
                or self._func_elem_nested_collection(bound.type)
            )
        )

    def _adopt_container_element_records(
        self, rhs_node: Any, bound_id: str
    ) -> None:
        """`fs := []func(){cl}` — an element naming an existing func
        value carries that value's captures and write targets into
        the container like a literal element's own records do. The
        container snapshots `cl`'s CURRENT records: a later `cl =`
        rebind does not change which function the slot holds."""
        body = rhs_node.child_by_field_name("body")
        if body is None:
            return
        stack = []
        # Go continues the implicit index after each keyed element —
        # `[]func{1: a, b}` puts `b` at index 2, not 1 — so the slot
        # counter follows the running index, not the position.
        next_index = 0
        for element in body.named_children:
            slot = f"i:{next_index}"
            next_index += 1
            if element.type == "keyed_element":
                key_node = element.child_by_field_name("key")
                value_node = element.child_by_field_name("value")
                if key_node is not None:
                    key_slot = self._func_elem_slot_key(key_node)
                    slot = (
                        key_slot
                        if key_slot is not None
                        else "r:" + key_node.text.decode(
                            "utf-8", errors="replace"
                        )
                    )
                    if key_slot is not None and key_slot.startswith(
                        "i:"
                    ):
                        # A keyed element reseats the implicit index —
                        # `[]func{1: a, b}` puts `b` at index 2.
                        next_index = int(key_slot[2:]) + 1
                if value_node is not None:
                    stack.append((value_node, slot))
            else:
                stack.append((element, slot))
        while stack:
            el, slot_key = stack.pop()
            if el.type == "func_literal":
                # A literal element records under the container
                # itself during eval — its inner identifiers are
                # captures, not elements.
                continue
            if el.type in {"identifier", "selector_expression"}:
                ref = self.references.get(self.node_key(el))
                src = ref.binding_id if ref is not None else None
                if src and src != bound_id:
                    self._adopt_element_records(src, bound_id)
                    src_bound = self.bindings.get(src)
                    if (
                        el.type == "identifier"
                        and src_bound is not None
                        and self._func_elem_collection(src_bound.type)
                        and src_bound.type.kind in {"slice", "map"}
                    ):
                        # `fm := [][]func{fs}` — the inner slot shares
                        # `fs`'s backing. Slices and maps are the only
                        # aliasing element carriers: a Go array
                        # literal copies (`fm := [][1]func{fs}`
                        # embeds a copy), so sharing it would
                        # propagate `fm[i][j]` writes back into `fs`.
                        # Only the slot the element initialized
                        # aliases it — `fm := [][]func{fs}` leaves
                        # `fm[1]` a fresh inner slice — so the donor
                        # is recorded per slot, not shared wholesale.
                        if slot_key is not None:
                            self._func_elem_inner_donors.setdefault(
                                bound_id, {}
                            ).setdefault(slot_key, set()).add(src)
                        else:
                            self._func_elem_share(src, bound_id)
                # A selector's operand (`st` in `st.M`) names no
                # element — skip its children like an identifier's.
                continue
            child_slot = (
                slot_key if el.type == "literal_element" else None
            )
            stack.extend((c, child_slot) for c in el.children)

    def _adopt_element_records(self, src: str, bound_id: str) -> None:
        """Union one func value's captures and write targets into a
        container binding — `fs[i] = f` behaves like an element
        inside `fs := []func(){f}`."""
        captured = self.closure_captures.get(src)
        if captured:
            self.closure_captures[bound_id] = (
                self.closure_captures.get(bound_id, frozenset())
                | captured
            )
        writes = self.closure_writes.get(src)
        if writes:
            self.closure_writes[bound_id] = (
                self.closure_writes.get(bound_id, frozenset()) | writes
            )
        if src in self.closure_star_writes:
            self.closure_star_writes.add(bound_id)
        if src in self.closure_inner_calls:
            self.closure_inner_calls.add(bound_id)

    def _func_elem_index_target(
        self, lhs: Any, locals_: dict[str, frozenset[int]]
    ) -> tuple[Any, Any | None, Any | None] | None:
        """`fs[i]` — an index store whose operand names a bound
        func-element container local. Returns (ref, index_node,
        inner_index_node), or None when the operand is not a local
        `[]func`/`[N]func`/`map[K]func` binding — nor one level of
        nesting (`fm[k][i]`, whose elements conflate under the root
        `fm` binding; inner_index_node is `k` then). A param
        container stays closed: its elements live in caller memory,
        which is an external mutation the local model cannot track."""
        if lhs is None or lhs.type != "index_expression":
            return None
        operand = lhs.child_by_field_name("operand")
        while (
            operand is not None
            and operand.type == "parenthesized_expression"
        ):
            operand = operand.child_by_field_name("operand")
        if operand is None:
            return None
        if operand.type == "identifier":
            ref = self.references.get(self.node_key(operand))
            if ref is None or ref.binding_id not in locals_:
                return None
            bound = self.bindings.get(ref.binding_id)
            if bound is None or not self._func_elem_collection(
                bound.type
            ):
                return None
            return ref, lhs.child_by_field_name("index"), None
        nested = self._func_elem_nested_operand(operand)
        if nested is None:
            return None
        root_id, _inner_id, inner_index = nested
        if root_id not in locals_:
            return None
        ref = self.references.get(self.node_key(_inner_id))
        if ref is None:
            return None
        return ref, lhs.child_by_field_name("index"), inner_index

    def _func_elem_append_target(
        self, node: Any, locals_: dict[str, frozenset[int]]
    ) -> str | None:
        """`append(fs, ...)` — the builtin append whose first argument
        names a bound func-element container local. Returns the
        container's binding id, or None for any other call shape. A
        param container stays closed like an element store does: its
        elements live in caller memory."""
        while (
            node is not None and node.type == "parenthesized_expression"
        ):
            node = next(
                (
                    c
                    for c in node.named_children
                    if c.type != "comment"
                ),
                None,
            )
        if node is None or node.type != "call_expression":
            return None
        call = self.calls.get(self.node_key(node))
        if call is None or call.kind != "builtin":
            return None
        function_node = node.child_by_field_name("function")
        while (
            function_node is not None
            and function_node.type == "parenthesized_expression"
        ):
            function_node = next(
                iter(function_node.named_children), None
            )
        if function_node is None or function_node.text != b"append":
            return None
        arguments_node = node.child_by_field_name("arguments")
        arguments = (
            _children(arguments_node) if arguments_node is not None else []
        )
        if len(arguments) < 2:
            return None
        arg0 = arguments[0]
        while (
            arg0 is not None and arg0.type == "parenthesized_expression"
        ):
            arg0 = next(iter(arg0.named_children), None)
        if arg0 is None or arg0.type != "identifier":
            return None
        ref = self.references.get(self.node_key(arg0))
        if ref is None or ref.binding_id not in locals_:
            return None
        bound = self.bindings.get(ref.binding_id)
        if bound is None or not self._func_elem_collection(bound.type):
            return None
        return ref.binding_id

    def _func_elem_share(
        self,
        binding_id: str,
        src_id: str,
        src_toks: frozenset[str] | None = None,
    ) -> None:
        """`fs2 := fs` / `fs2 = fs` between func-element containers —
        the copy shares the backing, so element stores through either
        name union into both record sets."""
        if binding_id == src_id:
            return
        self._func_elem_groups.setdefault(binding_id, set()).add(src_id)
        self._func_elem_groups.setdefault(src_id, set()).add(binding_id)
        # Register the operand's own token so sharer lookups stay
        # symmetric — `fs[0]` and `fs2[0]` see each other's writes.
        self._func_elem_tokens.setdefault(src_id, frozenset({src_id}))
        self._func_elem_tokens[binding_id] = (
            self._func_elem_tokens.get(binding_id, frozenset())
            | (
                src_toks
                if src_toks is not None
                else self._func_elem_eval_tokens(src_id)
            )
        )

    def _func_elem_eval_tokens(self, binding_id: str) -> frozenset[str]:
        """The backing instances `binding_id` may point at — its own
        id when nothing tracks it (the name's first backing)."""
        return self._func_elem_tokens.get(
            binding_id, frozenset({binding_id})
        )

    def _func_elem_sharers(self, binding_id: str) -> set[str]:
        """Every name whose backing set intersects `binding_id`'s —
        transitive through token identity, unlike `groups` edges
        which only list direct partners."""
        toks = self._func_elem_eval_tokens(binding_id)
        return {
            member_id
            for member_id, member_toks in self._func_elem_tokens.items()
            if member_toks & toks
        } | {binding_id}

    def _func_elem_slot_key(self, node: Any) -> str | None:
        """Canonical slot key for a literal index/key node —
        `1`, `0x1` and `'\\x01'` name the same Go element, `"a"`
        and `` `a` `` the same map key. Integer-kind keys carry an
        `i:` tag, string-kind an `s:` tag, anything else `r:` with
        the raw text. None for a non-literal (computed) node."""
        while node.type == "literal_element" and node.named_children:
            node = node.named_children[0]
        text = node.text.decode("utf-8", errors="replace")
        if node.type == "int_literal":
            value = _go_int_literal(text)
            return f"i:{value}" if value is not None else f"r:{text}"
        if node.type == "rune_literal":
            value = _go_rune_literal(text)
            return f"i:{value}" if value is not None else f"r:{text}"
        if node.type == "interpreted_string_literal":
            return f"s:{_go_interpreted_string(text)}"
        if node.type == "raw_string_literal":
            return f"s:{text[1:-1]}"
        if node.type in {"float_literal", "imaginary_literal"}:
            return f"r:{text}"
        return None

    def _func_elem_slot_donors(
        self, binding_id: str, inner_index: Any
    ) -> set[str]:
        """`fm[k]` — the bindings whose slice/map backing the inner
        slot aliases, recorded per composite element position
        (`fm := [][]func{fs}` -> slot "0" holds {fs}). A literal
        index resolves its own slot; a computed index may hit any
        element so every donor unions in. Donors resolve live
        through each container's current share group, so `fm2 := fm`
        sees `fm`'s donors without copying the table."""
        members = self._func_elem_sharers(binding_id)
        literal_key = (
            self._func_elem_slot_key(inner_index)
            if inner_index is not None
            and inner_index.type in _INDEX_LITERALS
            else None
        )
        donors: set[str] = set()
        for member_id in members:
            slots = self._func_elem_inner_donors.get(member_id)
            if not slots:
                continue
            if literal_key is None:
                for slot_donors in slots.values():
                    donors |= slot_donors
            else:
                donors |= slots.get(literal_key, set())
        donors.discard(binding_id)
        return donors

    def _func_elem_reseat(
        self, binding_id: str, prestate: tuple | None = None
    ) -> None:
        """A non-append reseat (`fs = mk()`, `fs = []func(){…}`,
        `fs = nil`) hands the name a fresh backing — the OLD
        elements stay reachable through names that shared it, so
        the binding's element records union onto each alias before
        the records clear; then the name leaves the group. When the
        caller passes the pre-RHS-eval snapshot (`prestate`), the
        sharers receive only the OLD records — a literal the RHS
        just recorded under this name belongs to the NEW backing."""
        surviving = set(self._func_elem_groups.get(binding_id, ()))
        if prestate is not None:
            captured = prestate[0].get(binding_id)
            writes = prestate[1].get(binding_id)
            starred = binding_id in prestate[2]
            called = binding_id in prestate[3]
        else:
            captured = self.closure_captures.get(binding_id)
            writes = self.closure_writes.get(binding_id)
            starred = binding_id in self.closure_star_writes
            called = binding_id in self.closure_inner_calls
        for member_id in self._func_elem_groups.pop(binding_id, set()):
            members = self._func_elem_groups.get(member_id)
            if members is not None:
                members.discard(binding_id)
                if not members:
                    self._func_elem_groups.pop(member_id, None)
            if captured:
                self.closure_captures[member_id] = (
                    self.closure_captures.get(member_id, frozenset())
                    | captured
                )
            if writes:
                self.closure_writes[member_id] = (
                    self.closure_writes.get(member_id, frozenset())
                    | writes
                )
            if starred:
                self.closure_star_writes.add(member_id)
            if called:
                self.closure_inner_calls.add(member_id)
        # The name leaves its old backing for a fresh one — hand it
        # a brand-new token so a default `binding_id` token cannot
        # collide with the backing the name just detached from.
        self._func_elem_token_seq += 1
        self._func_elem_tokens[binding_id] = frozenset(
            {f"{binding_id}#{self._func_elem_token_seq}"}
        )
        # The name leaves its container backing — donor sets naming
        # it (`fm := [][]func{fs}` slot 0) still alias the OLD
        # backing, so swap the name for the group members that keep
        # sharing it; the container's own donor table drops with it.
        inner_donors = self._func_elem_inner_donors.pop(
            binding_id, None
        )
        surviving.discard(binding_id)
        replacement = surviving
        if not surviving:
            # No live name shares the old backing — park its element
            # records under a surrogate id the donor sets can still
            # resolve, or `fm[0][i]` loses every element the old
            # slice carried.
            # Unique per reseat: the same variable can detach
            # twice (`fs = mk(); fs = mk2()`) and each abandoned
            # backing parks under its own surrogate, so a nested
            # container aliasing the FIRST backing does not see
            # the second's elements.
            self._func_elem_surrogate_seq += 1
            surrogate = (
                binding_id + "/func_elem/"
                + str(self._func_elem_surrogate_seq)
            )
            replacement = {surrogate}
            if captured:
                self.closure_captures[surrogate] = captured
            if writes:
                self.closure_writes[surrogate] = writes
            if starred:
                self.closure_star_writes.add(surrogate)
            if called:
                self.closure_inner_calls.add(surrogate)
            if inner_donors:
                self._func_elem_inner_donors[surrogate] = inner_donors
            if binding_id in self.opaque_callees:
                self.opaque_callees.add(surrogate)
        for slots in self._func_elem_inner_donors.values():
            for donor_set in slots.values():
                if binding_id in donor_set:
                    donor_set.discard(binding_id)
                    donor_set |= replacement

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

    def _method_value_parts(
        self, node: Any
    ) -> tuple[str, str | None, str | None] | None:
        """`(method binding id, receiver binding id | None, type
        operand type_id | None)` of a method value — `s.M` binds the
        receiver identifier, `St.M` (a type-name operand, a method
        *expression*) carries no receiver but keeps the operand's
        type identity so the call can pin it — or None when the
        selector isn't one.

        The field must resolve to a same-package method record
        (receiver non-null) and the operand — parens unwrapped —
        to a bare identifier; a computed operand (`g().M`) binds no
        stable receiver, so it stays closed.
        """
        if node is None or node.type != "selector_expression":
            return None
        field = node.child_by_field_name("field")
        field_ref = (
            self.references.get(self.node_key(field))
            if field is not None
            else None
        )
        method_fn = (
            self.functions.get(field_ref.binding_id)
            if field_ref is not None
            else None
        )
        if method_fn is None or method_fn.receiver is None:
            return None
        operand = node.child_by_field_name("operand")
        while (
            operand is not None
            and operand.type == "parenthesized_expression"
        ):
            operand = next(
                (c for c in operand.named_children if c.type != "comment"),
                None,
            )
        if operand is None or operand.type != "identifier":
            return None
        operand_ref = self.references.get(self.node_key(operand))
        if operand_ref is None:
            return None
        operand_binding = self.bindings.get(operand_ref.binding_id)
        if (
            operand_binding is not None
            and operand_binding.kind == "type"
        ):
            # `St.M` — a method *expression* value: no receiver
            # binding exists at the bind site; the caller passes it
            # as argument 0 like `St.M(st, args)` does. The operand's
            # type identity rides along so a call through the value
            # pins the type whose method set resolved the callee —
            # `f := Alias.M` stays a dependent of `Alias`.
            return (
                method_fn.binding_id,
                None,
                operand_binding.type.type_id,
            )
        return method_fn.binding_id, operand_ref.binding_id, None

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
        # Every named type the chain traverses pins — `st.A.N`
        # resolves `N` through `A`'s declared `type Q struct{...}`,
        # so redeclaring `Q` must flag `stale_dependents` like a root
        # or leaf change.
        for ident in resolved:
            if ident.type is not None:
                self._pin_fact_identities(ident.type)
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

        The boundary candidate must be a *top-level* declaration —
        one carrying a scope (the file or package extent, or an
        enclosing function body). Bindings nested inside the type
        declaration itself, like an interface method inside a
        field's type (`type P struct{ I interface{ M() }; V int64 }`),
        carry no scope, so they must not cut the field list short.
        """
        span = type_binding.span
        if span is None:
            return ()
        return self._fields_declared_after(span)

    def _fields_declared_after(self, span: Any) -> tuple[Any, ...]:
        """The field bindings declared in source order between
        `span.end` and the next scoped declaration — a named type's
        fields follow its name, and an anonymous `struct{...}`'s
        fields follow the declaring variable's (or field's) own
        name. A promoted field's binding lives inside its own
        declaring type's span, so it never appears in this window —
        which is what lets callers spot a write or read that must
        cross an embedded pointer."""
        type_file = span.file if isinstance(span, FileSpan) else 0
        boundary: int | None = None
        direct: list[Any] = []
        for b in self.bindings.values():
            bspan = b.span
            if bspan is None:
                continue
            bfile = bspan.file if isinstance(bspan, FileSpan) else 0
            if bfile != type_file or bspan.start <= span.end:
                continue
            is_field = b.kind == "variable" and b.scope is None
            if is_field:
                if boundary is None or bspan.start < boundary:
                    direct.append(b)
            elif b.scope is not None and (
                boundary is None or bspan.start < boundary
            ):
                boundary = bspan.start
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
        `var q Ptr` where `type Ptr *P` names no fields at all, and
        an imported container cannot be enumerated, so a write
        through it stays closed — reads remain sound under
        conflation. An anonymous `struct{...}` names no `type`
        member, but its fields still sit right after the declaring
        name's span, so the same source-order window enumerates them.
        """
        root_binding = self.bindings.get(ref.binding_id)
        if root_binding is None or root_binding.type is None:
            return False
        n = len(resolved_fields)
        for j in range(n):
            container_binding = (
                resolved_fields[j + 1]
                if j + 1 < n
                else root_binding
            )
            container_type = container_binding.type
            type_id = (
                container_type.type_id if container_type is not None else ""
            )
            if not type_id:
                # An anonymous `struct{...}` names no `type` member —
                # its fields still appear right after the declaring
                # variable's (or parent field's) own name span, so the
                # same source-order window enumerates them. A promoted
                # field's binding lives inside its own declaring
                # type's span, which a scoped declaration opens — it
                # never lands in this window.
                if (
                    container_type is None
                    or container_type.kind != "struct"
                ):
                    return False
                # A copy or a multi-name `var` declares the literal
                # after a different name — `cp := st` puts cp's fields
                # after st's name (or ITS anchor), and `var a, b
                # struct{...}` puts them after b's — so the window
                # anchors at the recorded span, not the container's.
                span = self.anon_struct_anchor.get(
                    container_binding.id
                ) or getattr(container_binding, "span", None)
                if span is None:
                    return False
                window = self._fields_declared_after(span)
                direct = {f.id for f in window}
                resolved = resolved_fields[j]
                if resolved.id in direct:
                    continue
                # Identical anonymous struct literals unify in the
                # type checker — `cp, z := struct{ V int64 }{...}, _`
                # resolves `cp.V` to the FIRST literal's field
                # binding, outside this window. Admit the unified
                # binding only when its name is a DIRECT field of
                # the anchored literal — a promoted field whose name
                # collides with a nested literal's inner field
                # stays closed.
                direct_names = self.anon_struct_field_names.get(
                    container_binding.id
                )
                if (
                    direct_names is None
                    or resolved.name not in direct_names
                ):
                    return False
                continue
            type_binding = self._pointee_type(type_id)
            span = getattr(type_binding, "span", None)
            if span is None:
                return False
            direct = {f.id for f in self._struct_fields(type_binding)}
            if resolved_fields[j].id not in direct:
                return False
        return True

    def _package_composite_field_read(
        self, node: Any
    ) -> tuple[Any, Any] | None:
        """The `(root var binding, leaf field identity)` of a field
        read `G.V` / `G.A.N` rooted at a package-level composite
        `var`. Package state is external like `lib.VS.F`: the read
        stays dep-free, so a pointer-typed intermediate field —
        which must stay closed inside a *local* composite's
        conflated set — is fine here: the deref reads package state
        either way."""
        fields: list[Any] = []
        extras: list[Any] = []
        cur = node
        saw_deref = False
        deref_operand = None
        while cur is not None:
            if cur.type == "parenthesized_expression":
                cur = next(
                    (c for c in cur.named_children if c.type != "comment"),
                    None,
                )
                continue
            if cur.type == "selector_expression":
                fields.append(cur.child_by_field_name("field"))
                cur = cur.child_by_field_name("operand")
                continue
            if cur.type == "index_expression":
                # `(*GA[i]).V` — the index evaluates for its side
                # effects like a write's does; the caller runs them.
                index = cur.child_by_field_name("index")
                if index is not None:
                    extras.append(index)
                cur = cur.child_by_field_name("operand")
                continue
            if cur.type == "unary_expression":
                operator = cur.child_by_field_name("operator")
                if operator is None or operator.text != b"*":
                    return None
                # `(*GP).V` spells `GP.V`'s sugar explicitly — the
                # deref peels the operand's declared pointer, still
                # external package state. `&` never reaches here —
                # it already closes at the `&` operator gate.
                if not saw_deref:
                    saw_deref = True
                    deref_operand = cur.child_by_field_name("operand")
                cur = cur.child_by_field_name("operand")
                continue
            break
        if cur is None or cur.type != "identifier" or cur.text == b"_":
            return None
        ref = self.references.get(self.node_key(cur))
        binding = (
            self.bindings.get(ref.binding_id)
            if ref is not None and ref.binding_id
            else None
        )
        derefed = (
            self._deref_operand_type(deref_operand, binding)
            if saw_deref and binding is not None
            else None
        )
        if (
            binding is None
            or binding.kind != "variable"
            or not self._package_level(binding)
            or not (
                self._is_local_composite(binding)
                or (
                    binding.type is not None
                    and binding.type.kind == "pointer"
                )
                or (
                    # `GA[i].V` / `M["k"].V` — a container var's
                    # indexed element's field: the descent's
                    # extras already evaluate the index, and the
                    # field resolves through its own reference like
                    # a struct field's does.
                    binding.type is not None
                    and binding.type.kind in {"slice", "array", "map"}
                    and fields
                )
                or (
                    derefed is not None
                    and derefed.kind == "pointer"
                )
            )
        ):
            return None
        resolved: list[Any] = []
        for field in fields:
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
            resolved.append(ident)
        if not resolved:
            return None
        if saw_deref and (
            derefed is None or derefed.kind != "pointer"
        ):
            # The deref must always peel a pointer — `(*GA[0]).V` on
            # `var GA []Q` derefs a non-pointer element and stays
            # closed even though the chain resolved.
            return None
        # Every named type the chain traverses pins: redeclaring an
        # intermediate field's type (`type Q struct{...}` for `G.A.N`)
        # must flag `stale_dependents` like a root or leaf change.
        for ident in resolved:
            if ident.type is not None:
                self._pin_fact_identities(ident.type)
        return binding, resolved[0], tuple(extras)

    def _deref_operand_type(self, node: Any, binding: Any) -> Any:
        """The type fact a `*` peels — the unary operand's declared
        type, walked from the root binding's own type.

        `(*GP).V` peels `GP`'s type, `(*G.P).V` the field `P`'s,
        `(*GA[0]).V` the slice element's, `(*GA[0].P).V` the
        element's field's. Components collect outermost-first and
        apply innermost-first onto the root's type: an index takes
        the container's `elem`, a selector the resolved field's
        declared type. Anything else in the operand (a call, another
        `*`) resolves to None — the chain stays closed."""
        ty = binding.type
        parts: list[Any] = []
        cur = node
        while cur is not None:
            if cur.type == "parenthesized_expression":
                cur = next(
                    (c for c in cur.named_children if c.type != "comment"),
                    None,
                )
                continue
            if cur.type == "selector_expression":
                parts.append(cur.child_by_field_name("field"))
                cur = cur.child_by_field_name("operand")
                continue
            if cur.type == "index_expression":
                parts.append(cur)
                cur = cur.child_by_field_name("operand")
                continue
            break
        if cur is None or cur.type != "identifier" or cur.text == b"_":
            return None
        for part in reversed(parts):
            if ty is None:
                return None
            if part.type == "index_expression":
                # `p[i]` on `*[]T` auto-derefs the pointer before
                # indexing — peel it, then take the element.
                if ty.kind == "pointer":
                    ty = ty.elem
                ty = ty.elem if ty is not None else None
                continue
            ref = self.references.get(self.node_key(part))
            ident = self._field_identity(ref)
            if ident is None:
                return None
            ty = ident.type
        return ty

    def _package_var_write(
        self, node: Any
    ) -> tuple[Any, tuple[Any, ...], bool] | None:
        """The package-level `var` an assignment LHS stores into —
        `G.V = v`, `G.A.N = v`, `G[i] = v`, `*GP = v` — mirroring
        `_imported_member_write`: the chain descends through
        parens/selectors/indexes/`*(saw_deref)` until a bare
        identifier names the var, whose own binding identity
        records the mutation (the stored deps drop — package state
        tracks no binding's contents). Index sub-expressions return
        as `extras` for evaluation like the imported path's."""
        cur = node
        while cur is not None and cur.type == "parenthesized_expression":
            cur = next(
                (c for c in cur.named_children if c.type != "comment"),
                None,
            )
        extras: list[Any] = []
        fields: list[Any] = []
        saw_deref = False
        deref_operand = None
        while cur is not None:
            if cur.type == "parenthesized_expression":
                cur = next(
                    (c for c in cur.named_children if c.type != "comment"),
                    None,
                )
                continue
            if cur.type == "unary_expression":
                operator = cur.child_by_field_name("operator")
                if operator is None or operator.text != b"*":
                    return None
                if not saw_deref:
                    saw_deref = True
                    deref_operand = cur.child_by_field_name("operand")
                cur = cur.child_by_field_name("operand")
                continue
            if cur.type == "selector_expression":
                fields.append(cur.child_by_field_name("field"))
                cur = cur.child_by_field_name("operand")
                continue
            if cur.type == "index_expression":
                index = cur.child_by_field_name("index")
                if index is not None:
                    extras.append(index)
                cur = cur.child_by_field_name("operand")
                continue
            if cur.type != "identifier" or cur.text == b"_":
                return None
            ref = self.references.get(self.node_key(cur))
            binding = (
                self.bindings.get(ref.binding_id)
                if ref is not None and ref.binding_id
                else None
            )
            if (
                binding is None
                or binding.kind != "variable"
                or not self._package_level(binding)
            ):
                return None
            resolved: list[Any] = []
            for field in fields:
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
                resolved.append(ident)
            fold = saw_deref
            if saw_deref:
                # The `*` peels its operand: `*G.P` dereferences the
                # field's pointer, `(*GP).V` the root var's,
                # `(*GA[0]).V` the index element's — whatever the
                # operand subtree resolves to. `*GP = v` on a
                # non-pointer var cannot compile, but rejecting
                # anyway stops a tampered binding from smuggling a
                # store past the gate.
                derefed = self._deref_operand_type(
                    deref_operand, binding
                )
                if derefed is None or derefed.kind != "pointer":
                    return None
            # Every named type the chain traverses pins — redeclaring
            # an intermediate field's type must flag
            # `stale_dependents` like a root or leaf change.
            for ident in resolved:
                if ident.type is not None:
                    self._pin_fact_identities(ident.type)
            if any(
                ident.type is not None
                and ident.type.kind == "pointer"
                for ident in resolved[1:]
            ):
                # `G.P.V = v` on `P *Q` crosses P's pointer — the
                # store may land in any binding `G.P = p` aimed at.
                fold = True
            return binding, tuple(extras), fold
        return None

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

    def _bound_field_chan(
        self,
        node: Any,
        locals_: dict[str, frozenset[int]],
        params: dict[str, int],
    ) -> tuple[tuple[Any, ...], Any, Any] | None:
        """`p.C` / `p.W.C` — a scalar-element `chan` field reached
        through a bound pointer (`p` a `*S` parameter or local).

        The queue lives in caller memory like the pointee itself, so
        a send/recv/close/range on it is an external mutation under
        the same model a `chan` parameter or package chan var uses:
        sends broadcast into `indirect_writes`, reads observe
        `deps(root) ∪ indirect_writes`, and every op records an
        imported transfer on the field member's identity. The
        returned triple mirrors `_bound_field_read`'s — the
        traversed `type` pointee members (for pinning), the leaf
        `chan` member, and the root identifier's reference — or
        None when the leaf is not a scalar-element `chan` var
        member."""
        inner = node
        while (
            inner is not None
            and inner.type == "parenthesized_expression"
        ):
            inner = next(
                (c for c in inner.named_children if c.type != "comment"),
                None,
            )
        if inner is None or inner.type != "selector_expression":
            return None
        operand = inner.child_by_field_name("operand")
        field = inner.child_by_field_name("field")
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
            or not self._scalar_chan_fact(field_member.type)
        ):
            return None
        return pointees, field_member, root_ref

    def _chan_queue_tokens(
        self,
        node: Any,
        locals_: dict[str, frozenset[int]],
        params: dict[str, int],
    ) -> frozenset[str] | None:
        """The queue identities a channel-typed RHS names — for a
        `p.C = ch` field store tracking which queue the member may
        now hold. A bare identifier yields its scalar-chan binding;
        a selector yields an external operand's target or a bound
        field member's live tokens. Anything else (`make(chan)` —
        a fresh queue whose contents the ordinary dep fold already
        carries, a call result, a receive) yields None."""
        inner = node
        while (
            inner is not None
            and inner.type == "parenthesized_expression"
        ):
            inner = next(
                (c for c in inner.named_children if c.type != "comment"),
                None,
            )
        if inner is None:
            return None
        if inner.type == "identifier":
            ref = self.references.get(self.node_key(inner))
            if ref is not None and self._scalar_chan_binding(
                ref.binding_id
            ):
                # `alias := ch; p.C = alias` — the field may hold the
                # queue `alias` resolves to, not `alias` itself:
                # record the alias root so a later `ch <- x` is
                # observed by `<-p.C`.
                return frozenset({self._chan_root(ref.binding_id)})
            return None
        external = self._external_chan_operand(inner, params)
        if external is not None:
            return frozenset({external[0]})
        field = self._bound_field_chan(inner, locals_, params)
        if field is not None:
            member = field[1]
            return self.field_chan_queues.get(
                member.id, frozenset({member.id})
            )
        return None

    def _field_chan_deps(
        self,
        member_id: str,
        locals_: dict[str, frozenset[int]],
        params: dict[str, int],
    ) -> frozenset[int]:
        """Deps of every queue a `chan` field member may hold — the
        member's own slot plus each token `p.C = ch` stores may have
        aliased it to (a may-set; over-approx like `escaped`)."""
        deps = locals_.get(member_id, frozenset())
        for token in self.field_chan_queues.get(member_id, ()):
            deps = deps | locals_.get(token, frozenset())
            if token in params:
                deps = deps | frozenset({params[token]})
        return deps

    def _bound_pointee_index_field(
        self,
        node: Any,
        locals_: dict[str, frozenset[int]],
        params: dict[str, int],
    ) -> tuple[Any, str, Any, tuple[Any, ...], Any, tuple[Any, ...], Any] | None:
        """`(*p)[i].F` — a field of the element a bound container
        pointee's index selects.

        Returns `(root identifier, pointee identity, innermost
        container fact, index nodes outermost-first, leaf field
        member, intermediate named-struct members, bound reference)`
        or None. The element the last level reaches must resolve the
        field through its own reference — a named struct's `var`
        member like `_bound_field_read`'s leaf, scalar-or-pointer.
        `(*p)[i].F.G` (and deeper: `.F.G.H`, …) admits arbitrary
        intermediate levels: each intermediate must be a `var`
        member whose named struct type pins, and the leaf resolves
        through its own reference like any leaf — an anonymous
        `struct{...}` intermediate stays closed.
        """
        operand = node.child_by_field_name("operand")
        field = node.child_by_field_name("field")
        if operand is None or field is None:
            return None
        while operand.type == "parenthesized_expression":
            operand = next(
                (c for c in operand.named_children if c.type != "comment"),
                None,
            )
            if operand is None:
                return None
        # Intermediate field selections (`(*p)[i].F.G` → `F`,
        # `(*p)[i].F.G.H` → `G` then `F`) collect leaf-adjacent
        # first: each must be a `var` member whose named struct type pins,
        # so a redeclaration of any traversed struct flags
        # `stale_dependents`. An anonymous `struct{...}` or a
        # scalar intermediate stops the chain (closed).
        mid_members: list[Any] = []
        while operand is not None and operand.type == "selector_expression":
            mid_operand = operand.child_by_field_name("operand")
            mid_field = operand.child_by_field_name("field")
            if mid_operand is None or mid_field is None:
                return None
            while mid_operand.type == "parenthesized_expression":
                mid_operand = next(
                    (
                        c
                        for c in mid_operand.named_children
                        if c.type != "comment"
                    ),
                    None,
                )
            if mid_operand is None:
                return None
            mid_ref = self.references.get(self.node_key(mid_field))
            if mid_ref is not None and mid_ref.kind == "import":
                mid_member = self.members.get(mid_ref.binding_id)
            else:
                mid_member = self._local_field(mid_ref)
            if (
                mid_member is None
                or mid_member.name.encode("utf-8") != mid_field.text
                or mid_member.kind not in {"var", "variable"}
                or mid_member.type is None
                or mid_member.type.kind != "struct"
                or not mid_member.type.type_id
            ):
                return None
            mid_members.append(mid_member)
            operand = mid_operand
        if operand.type != "index_expression":
            return None
        extras: list[Any] = []
        inner = operand
        while inner is not None and inner.type == "index_expression":
            idx = inner.child_by_field_name("index")
            if idx is not None:
                extras.append(idx)
            inner = inner.child_by_field_name("operand")
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
        ident = None
        if inner is not None and inner.type == "unary_expression":
            operator = inner.child_by_field_name("operator")
            sub = inner.child_by_field_name("operand")
            while (
                sub is not None
                and sub.type == "parenthesized_expression"
            ):
                sub = next(
                    (
                        c
                        for c in sub.named_children
                        if c.type != "comment"
                    ),
                    None,
                )
            if (
                operator is not None
                and operator.text == b"*"
                and sub is not None
                and sub.type == "identifier"
            ):
                ident = sub
        elif inner is not None and inner.type == "identifier":
            # `p[i].F` on `p *[N]T` — Go's auto-deref sugar for
            # pointer-to-array indexing.
            ident = inner
        if ident is None:
            return None
        bound = self._bound_container_pointee(ident, locals_, params)
        if bound is None:
            return None
        ref, pointee_id, fact = bound
        container_kinds = {"slice", "array", "map"}
        for _ in range(len(extras) - 1):
            if (
                fact is None
                or fact.kind not in container_kinds
                or fact.elem is None
            ):
                return None
            # Every level's own named identity pins so redeclaring
            # any traversed container type flags `stale_dependents`.
            if fact.type_id:
                self.pinned.add(fact.type_id)
            if fact.key is not None and fact.key.type_id:
                self.pinned.add(fact.key.type_id)
            fact = fact.elem
        if fact is None or fact.kind not in container_kinds:
            return None
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
            or field_member.type.kind
            not in {"integer", "boolean", "pointer"}
        ):
            return None
        return (
            ident,
            pointee_id,
            fact,
            tuple(extras),
            field_member,
            tuple(mid_members),
            ref,
        )

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
            if pointee.type.kind == "pointer":
                # `t.W` on a `W PP` field (`type PP *S`) — the named
                # pointer type's member IS the pointer; its whole
                # fact pins, and the pointee resolves one hop deeper
                # through its `elem`.
                self._pin_fact_identities(inner_field.type)
                pointee = self._pointer_underlying_pointee(
                    pointee, inner_field.id
                )
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
        if binding is None or binding.type.kind != "pointer":
            return None
        if binding.type.type_id:
            pointee = self._pointee_type(binding.type.type_id)
            if pointee is None:
                return None
            if pointee.type.kind == "pointer":
                # `p PP` on `type PP *T` — PP's member IS the pointer
                # type; its whole fact pins (PP and every identity
                # its elem tree names), and the pointee resolves one
                # hop deeper exactly like `p *T` does.
                self._pin_fact_identities(pointee.type)
                pointee = self._pointer_underlying_pointee(
                    pointee, ref.binding_id
                )
                if pointee is None:
                    return None
            return (pointee,), ref
        # `t *struct{...}` — an anonymous struct pointee names no
        # `type` member, but the pointee fact still classifies the
        # shape and each field resolves through its own binding.
        # A synthetic identity keeps the write side's transfer and
        # the pin honest — it can never redeclare, so it flags no
        # false staleness either.
        pointee_fact = binding.type.elem
        if pointee_fact is None or pointee_fact.kind != "struct":
            return None
        return (
            (
                _AnonymousPointee(
                    ref.binding_id + "/pointee", pointee_fact
                ),
            ),
            ref,
        )

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
            children = tuple(
                c for c in node.named_children if c.type != "comment"
            )
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
            inner = next(
                (
                    c
                    for c in node.named_children
                    if c.type != "comment"
                ),
                None,
            )
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
                if elem.type != "comment"
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

    def _pin_struct_fields(self, node: Any) -> bool:
        """Pin the declared type of every field a `struct{...}`
        literal lists — `new(struct{...})` admits only when each
        field pins cleanly, so a nested literal, a signature field
        or an unresolvable name keeps the call closed through the
        ordinary `_pin_type_node` gate."""
        decls = next(
            (
                c
                for c in node.named_children
                if c.type == "field_declaration_list"
            ),
            None,
        )
        if decls is None:
            return False
        return all(
            self._pin_type_node(field.child_by_field_name("type"))
            for field in decls.named_children
            if field.type == "field_declaration"
        )

    def result(
        self,
        fn: Function,
        dependencies: frozenset[int] | None = None,
        calls: tuple[CallTransfer, ...] = (),
        gaps: tuple[SummaryGap, ...] = (),
        pinned: tuple[str, ...] = (),
        statement_reads: tuple[StatementRead, ...] = (),
    ) -> FunctionSummary:
        key = hashlib.sha256((self.key + ":" + fn.binding_id).encode()).hexdigest()
        return FunctionSummary(
            fn.binding_id,
            key,
            tuple(
                p.type
                for p in (
                    (fn.receiver, *fn.parameters)
                    if fn.receiver is not None
                    else fn.parameters
                )
            ),
            fn.results[0].type if len(fn.results) == 1 else None,
            dependencies,
            calls,
            gaps,
            pinned,
            statement_reads,
        )

    def _pin_member_type(self, member: PackageMember) -> None:
        """Pin an admitted member's declared named-type identity.

        The producer names an imported `Named`/`Alias` type by the
        identity the imported unit's own report assigns it, so pinning
        it lets `stale_dependents` flag this summary when the type —
        not just the member — is redeclared.

        A pointer var's `pointee_type_ids` pin on reads too, not only
        on the `*lib.V = v` write path — `*lib.V` on a `var V PP`
        (`type PP *T`) records PP as the transfer identity, leaving T
        reachable only through the pointee ids the producer
        declared.
        """
        if member.type.type_id:
            self.pinned.add(member.type.type_id)
        pointee_ids = getattr(member, "pointee_type_ids", None)
        if pointee_ids:
            self.pinned.update(pointee_ids)

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
            if idx.type in _INDEX_LITERALS:
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
        # stays closed: strings have no container fact; a call operand
        # (`g(a)[i]` / `lib.G(a)[i]`) admits only when the declared
        # single-result type names a container with a scalar
        # element — its element provenance is the call's own dep
        # set — and any other computed operand (`f()[i]` without a
        # declared result type) names no member. The comma-ok form
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
        package_var = None
        bound_pointer = None
        bound_operand = None
        package_pointee = None
        call_operand = None
        call_fact = None
        call_member = None
        if inner is not None and inner.type == "selector_expression":
            member = self._package_member(inner)
        elif inner is not None and inner.type in (
            "call_expression",
            "type_conversion_expression",
        ):
            # `g(a)[i]` — an index read on a call result: the declared
            # result type must name a container whose element is
            # scalar. The element's provenance is the call's own dep
            # set (evaluated below) plus each index's deps — the
            # returned container is callee-produced memory, not
            # external state, so no imported transfer applies beyond
            # the call's own.
            call_member, call_fact = self._call_result_fact(inner)
            if call_fact is not None:
                call_operand = inner
        elif inner is not None and inner.type == "unary_expression":
            # `(*p)[i]` — an index read through a bound pointer whose
            # pointee is a container. The chain root is the `*p`
            # deref, so the operand must name an identifier binding.
            operator = inner.child_by_field_name("operator")
            sub = inner.child_by_field_name("operand")
            while (
                sub is not None
                and sub.type == "parenthesized_expression"
            ):
                sub = next(
                    (
                        c
                        for c in sub.named_children
                        if c.type != "comment"
                    ),
                    None,
                )
            if (
                operator is not None
                and operator.text == b"*"
                and sub is not None
                and sub.type == "identifier"
            ):
                bound_pointer = self._bound_container_pointee(
                    sub, locals_, params
                )
                bound_operand = sub
                if bound_pointer is None:
                    # `(*GP)[i]` on `var GP *[]T` — a package-level
                    # pointer var to a container pointee reads
                    # external memory like `GA[i]` does: dep-free,
                    # with the var's own identity recording the read.
                    package_pointee = self._package_container_pointee(
                        sub
                    )
        elif inner is not None and inner.type == "identifier":
            ref = self.references.get(self.node_key(inner))
            if ref is not None and ref.kind == "import":
                candidate = self.members.get(ref.binding_id)
                if (
                    candidate is not None
                    and candidate.name.encode("utf-8") == inner.text
                ):
                    member = candidate
            elif ref is not None and ref.binding_id:
                # `G[i]` — a package-level container var reads like an
                # imported member does: external state no binding
                # tracks, so the result stays dep-free while the
                # var's own identity records the read.
                package_var = self._package_container_var(inner)
                if package_var is None:
                    # `p[i]` on `p *[N]T` — Go's auto-deref sugar
                    # for pointer-to-array indexing reads through
                    # the bound pointer the same way `(*p)[i]` does.
                    bound_pointer = self._bound_container_pointee(
                        inner, locals_, params
                    )
                    bound_operand = inner
                    if bound_pointer is None:
                        # `GP[i]` on `var GP *[N]T` — the package
                        # var's own identity records the read.
                        package_pointee = (
                            self._package_container_pointee(inner)
                        )
        # Descend one `elem` fact per extra index level — `[][]T`
        # yields `[]T` then `T`. Every container's own named identity
        # pins at its level (a named `[]T` element, a map key).
        container_kinds = {"slice", "array", "map"}
        fact = (
            member.type
            if member is not None
            else (
                package_var.type
                if package_var is not None
                else (
                    bound_pointer[2]
                    if bound_pointer is not None
                    else (
                        package_pointee[1]
                        if package_pointee is not None
                        else (
                            call_fact
                            if call_operand is not None
                            else None
                        )
                    )
                )
            )
        )
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
            or (
                member is None
                and package_var is None
                and bound_pointer is None
                and package_pointee is None
                and call_operand is None
            )
            or (member is not None and member.kind != "var")
            or fact is None
            or fact.kind not in container_kinds
            or elem is None
            or elem.kind not in {"integer", "boolean", "pointer"}
        ):
            raise _Unsupported("non_parameter_reference", _span(node))
        if member is not None:
            self._pin_member_type(member)
        elif package_var is not None:
            self._pin_fact_identities(package_var.type)
        elif bound_pointer is not None:
            # `(*p)[i]` — the pointee's container fact pins its
            # declared identities; the synthetic `{binding}/pointee`
            # identity is never pinnable, and a named pointee's
            # `type_id` already sits inside the fact.
            self._pin_fact_identities(bound_pointer[2])
        elif call_operand is not None:
            # `g(a)[i]` — the declared result container/element
            # identities pin so a signature change flags the caller.
            self._pin_fact_identities(call_fact)
        else:
            # `(*GP)[i]` — same pins on the pointee container fact;
            # the var's own identity is the transfer target below.
            self._pin_fact_identities(package_pointee[1])
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
        if call_operand is None:
            transfers.append(
                CallTransfer(
                    FileSpan(self.current_file, node.start_byte, node.end_byte),
                    (
                        member.id
                        if member is not None
                        else (
                            package_var.id
                            if package_var is not None
                            else (
                                bound_pointer[1]
                                if bound_pointer is not None
                                else package_pointee[0]
                            )
                        )
                    ),
                    (),
                    frozenset(),
                    imported=True,
                )
            )
        deps = frozenset()
        if call_operand is not None and call_member is not None:
            # `lib.G(a)[i]` — the composite result keeps the call
            # `external_or_bodyless`: the minimal opaque fold a
            # `direct_import` applies — every argument's deps, the
            # chan/pointer write broadcast, the imported transfer on
            # the member's own identity and its signature pins.
            call_args = next(
                (
                    c
                    for c in call_operand.named_children
                    if c.type == "argument_list"
                ),
                None,
            )
            arg_nodes = tuple(
                c
                for c in (call_args.named_children if call_args else ())
                if c.type != "comment"
            )
            actual = tuple(
                self.expression(
                    arg, fn, params, locals_, transfers, count,
                    depth + 1,
                )
                for arg in arg_nodes
            )
            result = (
                frozenset().union(*actual) if actual else frozenset()
            )
            deps |= result
            call_node = self.calls.get(self.node_key(call_operand))
            if call_node is not None:
                # The call runs opaque for the summary-aware-calls
                # counter too — same accounting `expression` applies
                # to a bodyless callee.
                self._opaque_spans.add(_key3(call_node.span))
            transfers.append(
                CallTransfer(
                    (
                        call_node.span
                        if call_node is not None
                        else FileSpan(
                            self.current_file,
                            call_operand.start_byte,
                            call_operand.end_byte,
                        )
                    ),
                    call_member.id,
                    actual,
                    result,
                    imported=True,
                )
            )
            self._store_call_writes(
                list(arg_nodes), result, locals_, params
            )
            deps |= self._promote_chan_call_args(
                call_operand, "", locals_, params
            )
            self.pinned.update(
                getattr(call_member, "signature_type_ids", ()) or ()
            )
            self.pinned.update(
                getattr(call_node, "type_arg_type_ids", ())
            )
            # `lib.G(h, x)[i]` — a func-typed argument may run inside
            # the opaque callee. The argument reads queue the possible
            # invocations, but the call node itself never passes
            # through `expression` here, so drain them like the call's
            # own exit does (this also pops the accumulated
            # `_call_arg_deps` for the call's key).
            self._fold_func_arg_invocations(
                call_operand, params, locals_, transfers
            )
        elif call_operand is not None:
            # `g(a)[i]` — the call evaluates first in Go's order; the
            # element read carries its whole dep set.
            deps |= self.expression(
                call_operand, fn, params, locals_, transfers, count,
                depth + 1,
            )
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
        if bound_pointer is not None:
            # `(*p)[i]` — the loaded element also depends on where
            # the pointer was aimed (its own deps) and on every
            # earlier indirect store. An escaped binding can never be
            # this pointee (a bound pointer cannot alias a local
            # composite — `&s`/`&st` stay closed), so unlike a bare
            # `*p` scalar deref no escaped union applies.
            base = self.expression(
                bound_operand, fn, params, locals_, transfers, count,
                depth + 1,
            )
            deps |= base | self.indirect_writes
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

    def _package_container_var(self, node: Any) -> Any | None:
        """The package-level `var` a range/index operand names — a
        bare identifier (or parens) bound to a slice, array or map
        kind. Anything else resolves to no binding and the caller
        falls back to the ordinary expression gate, exactly like the
        imported-member variant.
        """
        inner = node
        while inner is not None and inner.type == "parenthesized_expression":
            inner = next(
                (c for c in inner.named_children if c.type != "comment"),
                None,
            )
        if inner is None or inner.type != "identifier" or inner.text == b"_":
            return None
        ref = self.references.get(self.node_key(inner))
        binding = (
            self.bindings.get(ref.binding_id)
            if ref is not None and ref.binding_id
            else None
        )
        if (
            binding is not None
            and binding.kind == "variable"
            and self._package_level(binding)
            and binding.type is not None
            and binding.type.kind in {"slice", "array", "map"}
        ):
            return binding
        return None

    def _bind_range_names(
        self,
        names: list[Any],
        scope: dict[str, frozenset[int]],
        params: dict[str, int],
        conditional: bool,
        value_deps: frozenset[int] = frozenset(),
        key_deps: frozenset[int] = frozenset(),
    ) -> None:
        """Bind `for` range names to dep-free (external-state) values.

        `_` slots skip; a fresh `:=` name uses the compiler's binding
        record (its declared type must be scalar-or-pointer — a map's
        string key or a struct element stays closed); an `=` name
        reuses the referenced binding through `_store`. `value_deps`
        applies to the element name — the second of a two-name range
        — when the container lives in caller memory a bound pointer's
        aim selects (`for range *p`): those elements carry the
        pointer's own and the indirect stores' deps like `(*p)[i]`.
        `key_deps` applies to the first name when the ranged
        container is a map whose entries a call produced — the key
        is stored data like the element, not an index position.
        """
        for pos, name in enumerate(names):
            if name.text == b"_":
                continue
            deps = value_deps if pos == 1 else key_deps
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
                scope[binding.id] = deps
                if binding.type.kind == "pointer":
                    # A pointer-typed range name's provenance is
                    # the element value — `for _, p = range *ps`.
                    self._ptr_deps[binding.id] = deps
            else:
                ref = self.references.get(self.node_key(name))
                if ref is None or (
                    ref.binding_id not in scope
                    and ref.binding_id not in params
                ):
                    raise _Unsupported(
                        "binding_unavailable", _span(name)
                    )
                rb = self.bindings.get(ref.binding_id)
                if rb is not None and rb.type.kind == "pointer":
                    new = deps
                    if conditional:
                        new = (
                            self._pointer_deps(
                                ref.binding_id, params, scope
                            )
                            | new
                        )
                    self._ptr_deps[ref.binding_id] = new
                self._store(
                    scope, params, ref.binding_id, deps, conditional,
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
            return self._comma_ok_map_call_operand(node)
        member, levels = resolved
        if member.kind != "var":
            return None
        fact = member.type
        for _ in range(levels):
            fact = fact.elem if fact is not None else None
        if fact is None or fact.kind != "map":
            return None
        return member

    def _comma_ok_map_call_operand(self, node: Any) -> Any | None:
        """`v, ok := lib.M(a)[\"k\"]` — the comma-ok pair on a call
        result's map element. The outermost index's own container
        must still be a map — one `elem` descent per inner level —
        and the read itself flows through `_imported_index_read`'s
        call operand arm, so only the arity and map shape gate here."""
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
        if inner is None or inner.type not in (
            "call_expression",
            "type_conversion_expression",
        ):
            return None
        _, fact = self._call_result_fact(inner)
        for _ in range(levels):
            fact = fact.elem if fact is not None else None
        if fact is None or fact.kind != "map":
            return None
        return node

    def _call_result_fact(self, node: Any) -> tuple[Any | None, Any | None]:
        """(member, single-result fact) for a call operand.

        `_call_result_type` covers the resolvable cases — a
        `direct_local`/method callee's declared `results[0].type` or
        a `direct_import` member's `result_types[0]`. An imported
        callee whose COMPOSITE result keeps the call
        `external_or_bodyless` still declares `result_types` on its
        member — the member resolves through the call's `function`
        selector because `call.target` never carried the member id
        for bodyless calls."""
        fact = self._call_result_type(node)
        if fact is not None:
            return None, fact
        if node.type != "call_expression":
            return None, None
        callee_node = node.child_by_field_name("function")
        while (
            callee_node is not None
            and callee_node.type == "parenthesized_expression"
        ):
            callee_node = next(
                (
                    c
                    for c in callee_node.named_children
                    if c.type != "comment"
                ),
                None,
            )
        candidate = (
            self._package_member(callee_node)
            if callee_node is not None
            and callee_node.type == "selector_expression"
            else None
        )
        call_node = self.calls.get(self.node_key(node))
        if (
            candidate is not None
            and getattr(candidate, "result_types", None)
            and call_node is not None
            and call_node.kind == "external_or_bodyless"
        ):
            return candidate, candidate.result_types[0]
        return None, None

    def _is_chan_recv(self, node: Any, width: int) -> bool:
        """`v, ok := <-ch` — the comma-ok receive shape. The receive
        itself evaluates through the ordinary `<-` path, which gates
        the channel operand; this only sizes the LHS arity."""
        if width != 2 or node is None or node.type != "unary_expression":
            return False
        operator = node.child_by_field_name("operator")
        return operator is not None and operator.type == "<-"

    def _select_receive_eval(
        self,
        node: Any,
        fn: Function,
        params: dict[str, int],
        locals_: dict[str, frozenset[int]],
        transfers: list[CallTransfer],
        count: list[int],
    ) -> tuple[list, Any, frozenset[int]]:
        """Evaluate a `communication_case` receive in the entry scope.

        `v := <-ch`, `v, ok := <-ch`, `v = <-ch`, `v, ok = <-ch` or a
        bare `<-ch`: Go evaluates the channel operand — and, with it,
        the receive's recorded deps — once, in source order, before
        any case is chosen, so this runs on the select's pre-state
        like a send's channel and value operands do. Returns the LHS
        nodes, the receive node (for diagnostics) and its deps; the
        bound names store later, inside the chosen alternative.
        """
        lefts: list = []
        recv = None
        for child in node.children:
            if child.type == "expression_list":
                lefts = _children(child)
            elif child.is_named:
                recv = child
        if recv is None:
            raise _Unsupported("unsupported_statement", _span(node))
        recv_deps = self.expression(
            recv, fn, params, locals_, transfers, count, 0
        )
        return lefts, recv, recv_deps

    def _select_receive_store(
        self,
        lefts: list,
        recv: Any,
        recv_deps: frozenset[int],
        node: Any,
        fn: Function,
        params: dict[str, int],
        locals_: dict[str, frozenset[int]],
        transfers: list[CallTransfer],
        count: list[int],
        conditional: bool,
    ) -> None:
        """Bind a select receive's LHS names inside the chosen case.

        Each bound name takes the receive's deps — the comma-ok flag
        conservatively shares them, matching `v, ok := <-ch`.
        Bare-identifier stores into locals admit like any `=`/`:=`;
        `G = <-ch`, `G.V = <-ch` or `lib.V = <-ch` mutate external
        state the same way the ordinary assignment admits — the
        var's or member's identity records the transfer and the
        received deps drop. A composite local's field (`s.V = <-ch`)
        stays closed.
        """
        # Go evaluates every LHS operand — index and call arguments
        # inside a composite write target — before any assignment
        # lands, so `i, GB[Set(&r, i)] = <-ch` must read the OLD `i`
        # inside `Set`'s arguments. Resolve every target and evaluate
        # its extras first, then perform the stores.
        pending: list[Any] = []
        for lhs in lefts:
            if lhs.text == b"_":
                pending.append(None)
                continue
            package_write = self._package_var_write(lhs)
            if package_write is not None:
                binding, extras, _ = package_write
                self._eval_write_extras(
                    extras, fn, params, locals_, transfers, count
                )
                pending.append(("package", lhs, binding, extras))
                continue
            member_write = self._imported_member_write(lhs)
            if member_write is not None:
                member, extras, _ = member_write
                self._eval_write_extras(
                    extras, fn, params, locals_, transfers, count
                )
                pending.append(("member", lhs, member, extras))
                continue
            # `s.V = <-ch` / `*p = <-ch` — a field store through a
            # pointer-typed binding or a local composite admits the
            # same way the ordinary assignment does: external memory
            # records the mutation, the received deps accumulate
            # into the base binding, and a declared-type base also
            # broadcasts into `indirect_writes`.
            write_target = self._opaque_write_target(
                lhs, locals_, params
            )
            if write_target is not None:
                type_id, ref, nested = write_target
                # The store's destination read mirrors `=`:
                # a bound-pointer base reads the pointer's
                # provenance (plus the indirect stores a nested
                # `t.W.f` traversal may read), while a tracked
                # local composite reads its continuing dep set.
                if type_id:
                    dest = self._pointer_deps(
                        ref.binding_id, params, locals_
                    )
                    if nested:
                        dest = dest | self.indirect_writes
                else:
                    dest = locals_.get(
                        ref.binding_id,
                        frozenset({params[ref.binding_id]})
                        if ref.binding_id in params
                        else frozenset(),
                    )
                self._record_read(dest)
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
                pending.append(
                    ("field", ref, bool(type_id), nested)
                )
                continue
            # `(*p)[i] = <-ch` — a store through a bound container
            # pointee writes element memory no binding tracks: the
            # received deps union into every escaped binding plus
            # `indirect_writes`, like the assignment's alias fold.
            bound_write = self._bound_container_write(
                lhs, locals_, params
            )
            if bound_write is not None:
                pointee_id, extras, fact, ref = bound_write
                dest_deps = self._pointer_deps(
                    ref.binding_id, params, locals_
                )
                self._record_read(dest_deps)
                self._pin_fact_identities(fact)
                for extra in reversed(extras):
                    if extra.type in _INDEX_LITERALS:
                        continue
                    self._record_read(
                        self.expression(
                            extra, fn, params, locals_,
                            transfers, count, 0,
                        )
                    )
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
                pending.append(("alias",))
                continue
            # `(*p)[i].F = <-ch` — a field store through the element a
            # bound container pointee's index selects: same alias fold,
            # the leaf field's identity records the mutation.
            indexed_field = self._bound_pointee_index_field(
                lhs, locals_, params
            )
            if indexed_field is not None:
                (
                    _root, _pid, fact, extras, field_member,
                    mid_members, ref,
                ) = indexed_field
                self._pin_fact_identities(fact)
                for mid_member in mid_members:
                    self._pin_fact_identities(mid_member.type)
                if field_member.type is not None:
                    self._pin_fact_identities(field_member.type)
                for extra in reversed(extras):
                    if extra.type in _INDEX_LITERALS:
                        continue
                    self._record_read(
                        self.expression(
                            extra, fn, params, locals_,
                            transfers, count, 0,
                        )
                    )
                self._record_read(
                    self._pointer_deps(ref.binding_id, params, locals_)
                )
                transfers.append(
                    CallTransfer(
                        FileSpan(
                            self.current_file,
                            lhs.start_byte,
                            lhs.end_byte,
                        ),
                        field_member.id,
                        (),
                        frozenset(),
                        imported=True,
                    )
                )
                pending.append(("alias",))
                continue
            # `*p = <-ch` — a store through a bound pointer lands in
            # untracked memory; the received deps fold into every
            # escaped binding plus `indirect_writes`, like `*p = v`.
            bound_ptr = self._bound_pointer_write(
                lhs, locals_, params
            )
            if bound_ptr is not None:
                pointee_id, ref, extra = bound_ptr
                self._record_read(
                    self._deref_read_deps(
                        ref.binding_id, params, locals_
                    )
                    if extra
                    else self._pointer_deps(
                        ref.binding_id, params, locals_
                    )
                )
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
                pending.append(("alias",))
                continue
            if lhs.type != "identifier":
                raise _Unsupported("unsupported_statement", _span(node))
            binding = self.bindings_by_span.get(self.node_key(lhs))
            if binding is None:
                ref = self.references.get(self.node_key(lhs))
                if ref is not None and ref.binding_id:
                    binding = self.bindings.get(ref.binding_id)
            if binding is None or binding.type.kind not in {
                "integer",
                "boolean",
                "pointer",
            }:
                raise _Unsupported("binding_unavailable", _span(node))
            pending.append(("local", binding))
        for entry in pending:
            if entry is None:
                continue
            if entry[0] == "package":
                _, lhs, binding, extras = entry
                self._record_package_write(
                    lhs, binding, extras, fn, params, locals_,
                    transfers, count, eval_extras=False,
                )
            elif entry[0] == "member":
                _, lhs, member, extras = entry
                self._record_member_write(
                    lhs, member, extras, fn, params, locals_,
                    transfers, count, eval_extras=False,
                )
            elif entry[0] == "field":
                _, ref, bcast, nested = entry
                base = (
                    locals_.get(ref.binding_id)
                    if ref.binding_id in locals_
                    else frozenset({params[ref.binding_id]})
                    if ref.binding_id in params
                    else frozenset()
                )
                self._store(
                    locals_, params, ref.binding_id,
                    base | recv_deps, conditional,
                )
                if bcast:
                    self.indirect_writes |= recv_deps
            elif entry[0] == "alias":
                self.indirect_writes |= recv_deps
                for escaped_id in self.escaped:
                    esc_base = (
                        locals_.get(escaped_id)
                        if escaped_id in locals_
                        else frozenset({params[escaped_id]})
                        if escaped_id in params
                        else frozenset()
                    )
                    self._store(
                        locals_, params, escaped_id,
                        esc_base | recv_deps, conditional,
                    )
            else:
                _, binding = entry
                # `:=` binds fresh names (and a reused one keeps the
                # skipped path's value under `conditional`), `=`
                # stores into the existing binding — `_store` already
                # gives the may-skip union semantics both need inside
                # a case.
                self._store(
                    locals_, params, binding.id, recv_deps, conditional
                )

    def _is_chan_binding(self, binding_id: str) -> bool:
        """The bound name's declared type is a channel."""
        binding = self.bindings.get(binding_id)
        return (
            binding is not None
            and binding.type is not None
            and binding.type.kind == "chan"
        )

    def _scalar_chan_binding(self, binding_id: str) -> bool:
        """The bound name is a `chan T` whose element is scalar.

        Only scalar-element channels admit: `chan chan T` would let a
        channel VALUE travel through a queue (`ch2, _ = <-q`) and
        alias it under a second dep set — the exact under-approx the
        make-only bind gate exists to prevent; a composite element
        binds into the unsupported composite-value shapes anyway.
        """
        binding = self.bindings.get(binding_id)
        elem = (
            binding.type.elem
            if binding is not None and binding.type is not None
            else None
        )
        return (
            binding is not None
            and binding.type is not None
            and binding.type.kind == "chan"
            and elem is not None
            and elem.kind in {"integer", "boolean"}
        )

    def _scalar_chan_fact(self, fact: Any) -> bool:
        """Whether `fact` is a `chan T` whose element is scalar —
        the binding-free twin of `_scalar_chan_binding` for declared
        result types, which carry facts rather than bindings."""
        return (
            fact is not None
            and fact.kind == "chan"
            and fact.elem is not None
            and fact.elem.kind in {"integer", "boolean"}
        )

    def _chan_binding(self, node: Any, locals_: dict, params: dict) -> Any:
        """The channel binding `node` names, or None.

        A channel local to the function admits under the conflated
        queue model; a `chan T` parameter admits under the external
        sync-resource model (send/recv/close touch a queue the
        caller shares — recorded as imported effects). A selector
        (`p.C`), a package-level channel or any other operand still
        names a queue the summary cannot model, so it stays closed.
        """
        while (
            node is not None and node.type == "parenthesized_expression"
        ):
            node = next(
                (c for c in node.named_children if c.type != "comment"),
                None,
            )
        if node is None or node.type != "identifier":
            return None
        ref = self.references.get(self.node_key(node))
        binding = (
            self.bindings.get(ref.binding_id)
            if ref is not None and ref.binding_id
            else None
        )
        if (
            binding is None
            or not self._scalar_chan_binding(binding.id)
            or (binding.id not in locals_ and binding.id not in params)
        ):
            return None
        return self.bindings.get(self._chan_root(binding.id))

    def _chan_root(self, binding_id: str) -> str:
        """Resolve a channel name's alias chain to the queue binding.

        `ch2 := ch` / `var ch2 = ch` / `ch2 = x` name the same queue,
        so every channel operation resolves through `chan_aliases`
        before the local-vs-parameter classification reads it. An
        unaliased name is its own root."""
        # `chan_aliases` stores the resolved queue — the binding id
        # of the channel the alias source stood for at admission —
        # not a next hop, so a single lookup resolves it. Walking
        # further misreads `a, b = b, a`: `a`'s queue legitimately
        # becomes `b`'s token while `b`'s becomes `a`'s, and a walk
        # turns that swap into a name cycle that resolves send and
        # receive to different slots.
        return self.chan_aliases.get(binding_id, binding_id)

    def _chan_alias_target(
        self, node: Any, locals_: dict, params: dict
    ) -> Any:
        """The binding `node` names when it can stand as a `ch2 := ch`
        alias source — an identifier bound to a scalar-element channel
        in locals or params. Anything else stays closed."""
        while node is not None and node.type == "parenthesized_expression":
            node = next(
                (c for c in node.named_children if c.type != "comment"),
                None,
            )
        if node is None or node.type != "identifier":
            return None
        ref = self.references.get(self.node_key(node))
        if ref is None or not ref.binding_id:
            return None
        source_id = self._chan_root(ref.binding_id)
        binding = self.bindings.get(source_id)
        if (
            binding is None
            or not self._scalar_chan_binding(binding.id)
            or (source_id not in locals_ and source_id not in params)
        ):
            return None
        return binding

    def _external_chan_operand(
        self, node: Any, params: dict
    ) -> Any | None:
        """The (target_id, fact) for a channel operand living in
        external state — a package-level `var GC chan T` or an
        imported member `lib.GC` — whose element is scalar. Sends,
        receives and closes on it touch a queue outside the
        function's locals, so they record imported transfers on the
        target's identity exactly like a `chan` parameter's ops."""
        inner = node
        while (
            inner is not None
            and inner.type == "parenthesized_expression"
        ):
            inner = next(
                (c for c in inner.named_children if c.type != "comment"),
                None,
            )
        if inner is None:
            return None
        if inner.type == "identifier":
            ref = self.references.get(self.node_key(inner))
            binding = (
                self.bindings.get(ref.binding_id)
                if ref is not None and ref.binding_id
                else None
            )
            fact = binding.type if binding is not None else None
            if (
                binding is not None
                and binding.kind == "variable"
                and self._package_level(binding)
                and (
                    self._scalar_chan_fact(fact)
                    or self._chan_chan_fact(fact)
                )
            ):
                return (binding.id, fact)
            # A dot-imported member — `VC` for `import . "lib"` —
            # names no binding: it resolves through the member record
            # like `lib.VC` does.
            member = self._imported_member_operand(inner)
            if member is not None and (
                self._scalar_chan_fact(member.type)
                or self._chan_chan_fact(member.type)
            ):
                return (member.id, member.type)
            # A `chan chan T` parameter or a name bound to an
            # external `chan chan` (a callee-produced `cc := g()`)
            # — the outer queue is caller-shared state, so ops on it
            # record imported effects on the binding's own identity
            # exactly like a scalar `chan` parameter's do.
            if (
                binding is not None
                and self._chan_chan_fact(fact)
                and (
                    ref.binding_id in params
                    or ref.binding_id in self.external_chan_locals
                )
            ):
                return (binding.id, fact)
            return None
        member = self._imported_member_operand(inner)
        if member is not None and (
            self._scalar_chan_fact(member.type)
            or self._chan_chan_fact(member.type)
        ):
            return (member.id, member.type)
        return None

    def _scalar_chan_fact(self, fact: Any) -> bool:
        """The fact is a `chan` type whose element is scalar —
        the admit gate `_scalar_chan_binding` applies to bindings,
        applied here to a package var's or member's declared type."""
        return (
            fact is not None
            and fact.kind == "chan"
            and fact.elem is not None
            and fact.elem.kind in {"integer", "boolean"}
        )

    def _chan_chan_fact(self, fact: Any) -> bool:
        """The fact is a `chan (chan T)` whose inner element T is
        scalar — a channel-of-channels exactly one level deep.

        The outer queue admits only under the external model: ops
        on a `chan chan T` parameter, a callee-produced `chan chan`
        name or a package-level one record imported effects against
        the operand's own identity, and a channel SENT into it
        (`cc <- ch`) is promoted into `external_chan_locals` because
        the queue hands `ch`'s contents to the caller's domain. A
        received channel (`c := <-cc`) binds dep-free as an external
        name through the same machinery. Deeper nesting
        (`chan chan chan T`) and local `make(chan chan T)` queues
        stay closed — a channel value flowing between two LOCAL
        queues would alias queues the conflated dep set cannot
        track."""
        return (
            fact is not None
            and fact.kind == "chan"
            and fact.elem is not None
            and fact.elem.kind == "chan"
            and fact.elem.elem is not None
            and fact.elem.elem.kind in {"integer", "boolean"}
        )

    def _chan_chan_receive(self, node: Any, params: dict) -> bool:
        """Whether `node` is `<-cc` receiving a channel value out of
        a `chan chan T` queue in external state — the received name
        binds an external queue of its own."""
        inner = node
        while (
            inner is not None
            and inner.type == "parenthesized_expression"
        ):
            inner = next(
                (c for c in inner.named_children if c.type != "comment"),
                None,
            )
        if inner is None or inner.type != "unary_expression":
            return False
        operator = inner.child_by_field_name("operator")
        if operator is None or operator.type != "<-":
            return False
        ext = self._external_chan_operand(
            inner.child_by_field_name("operand"), params
        )
        return ext is not None and self._chan_chan_fact(ext[1])

    def _calls_touch_external_chan(
        self,
        calls: Iterable[CallTransfer],
        pred: Any | None = None,
    ) -> bool:
        """A recorded transfer — or a local callee reachable through
        one — operates on a channel outside the caller's bindings.
        `mid(v) { inner(v) }` where `inner` sends on `GC` leaves the
        `GC` transfer inside `inner`'s summary, not `mid`'s, so the
        check walks the local call graph with a `seen` bound. `pred`
        overrides the per-target predicate (`_chan_chan_id` narrows
        the match to `chan chan` operands)."""
        check = pred or self._external_chan_id
        seen: set[str] = set()
        stack = list(calls)
        while stack:
            c = stack.pop()
            if check(c.target):
                return True
            if c.target in seen or c.target not in self.functions:
                continue
            seen.add(c.target)
            nested = self.summarize(c.target)
            if nested is not None and nested.available:
                stack.extend(nested.calls)
        return False

    def _external_chan_id(self, target_id: str) -> bool:
        """A transfer target naming an external `chan` operand —
        a package-level chan var's binding, an imported member, or
        a scope-less struct field's `chan` member — so a callee's
        recorded ops on it mean the caller shares the queue. A
        `chan chan` binding is shared at ANY scope: locals cannot
        declare the type, so the binding is a package var, a
        parameter, or a callee-produced name — all caller-visible
        state."""
        binding = self.bindings.get(target_id)
        if (
            binding is not None
            and binding.kind == "variable"
            and (
                self._chan_chan_fact(binding.type)
                or (
                    (
                        self._package_level(binding)
                        or binding.scope is None
                    )
                    and self._scalar_chan_fact(binding.type)
                )
            )
        ):
            return True
        member = self.members.get(target_id)
        return member is not None and (
            self._scalar_chan_fact(member.type)
            or self._chan_chan_fact(member.type)
        )

    def _chan_chan_id(self, target_id: str) -> bool:
        """A transfer target naming a `chan chan` operand —
        the outer queue is shared state at any scope (locals
        cannot declare the type)."""
        binding = self.bindings.get(target_id)
        if (
            binding is not None
            and binding.kind == "variable"
            and self._chan_chan_fact(binding.type)
        ):
            return True
        member = self.members.get(target_id)
        return member is not None and self._chan_chan_fact(member.type)

    def _chan_call_args(self, node: Any) -> Any | None:
        """The call's `argument_list` node, unwrapping parens —
        `ch, _ = (g(q))` must still see `q`."""
        inner = node
        while (
            inner is not None
            and inner.type == "parenthesized_expression"
        ):
            inner = next(
                (c for c in inner.named_children if c.type != "comment"),
                None,
            )
        if inner is None:
            return None
        if inner.type == "call_expression":
            args = inner.child_by_field_name("arguments")
            return args.named_children if args is not None else ()
        if self._elem_call_conversion(inner):
            # `fs[i](q)` — the conversion form carries arguments on
            # its `operand` field (an expression_list, or the single
            # argument itself) rather than an `argument_list`.
            operand = inner.child_by_field_name("operand")
            if operand is None:
                return ()
            return (
                operand.named_children
                if operand.type == "expression_list"
                else (operand,)
            )
        return None

    def _promote_chan_call_args(
        self,
        call_node: Any,
        exclude_id: str,
        locals_: dict[str, frozenset[int]],
        params: dict[str, int],
    ) -> frozenset[int]:
        """Promote every chan-typed argument's root queue to
        external and return the union of their contents — the
        callee may hand one of them back through a local alias
        (`r := q; return r`) the passthrough probe cannot see, so
        sends on the result name broadcast into those queues."""
        call_args = self._chan_call_args(call_node)
        return self._promote_chan_arg_roots(
            call_args if call_args is not None else (),
            exclude_id,
            locals_,
            params,
        )

    def _promote_chan_arg_roots(
        self,
        arguments: Iterable[Any],
        exclude_id: str,
        locals_: dict[str, frozenset[int]],
        params: dict[str, int],
    ) -> frozenset[int]:
        """The argument-list variant of `_promote_chan_call_args`
        for sites that hold the argument nodes rather than the
        call node (a bound-method or declared-callee fold)."""
        deps: frozenset[int] = frozenset()
        for arg in arguments:
            if arg.type == "comment":
                continue
            arg_root = self._chan_alias_target(arg, locals_, params)
            if (
                arg_root is not None
                and arg_root.id != exclude_id
            ):
                self.external_chan_locals.add(arg_root.id)
                arg_slot = locals_.get(arg_root.id)
                if (
                    arg_slot is None
                    and arg_root.id in params
                ):
                    arg_slot = frozenset({params[arg_root.id]})
                deps = deps | (arg_slot or frozenset())
        return deps

    def _captured_current_deps(
        self,
        captured: frozenset[str],
        params: dict[str, int],
        locals_: dict[str, frozenset[int]],
    ) -> frozenset[int]:
        """Resolve each captured binding's deps NOW — reassignments
        between the literal and the read move what a bound closure
        actually observes (`p := &a; h := func(){*p}; p = &b; h()`
        reads `b`, not `a`). `locals_` wins over the parameter index:
        `x = y` stores the param's current value under its binding id."""
        resolved: frozenset[int] = frozenset()
        for cbid in captured:
            # A captured channel name may have been reseated
            # between the literal and the read (`ch = ch2`) —
            # resolve the queue it names NOW, not the one its
            # own slot still holds.
            root = (
                self._chan_root(cbid)
                if self._is_chan_binding(cbid)
                else cbid
            )
            if root in locals_:
                resolved |= locals_[root]
                if root in self.external_chan_locals:
                    resolved |= self.indirect_writes
            elif root in params:
                resolved |= frozenset({params[root]})
            elif root in self._dead_local_deps:
                # A captured branch-local died at the merge — its
                # frozen deps are the value the stored closure sees.
                resolved |= self._dead_local_deps[root]
        return resolved

    def _return_expr_deps(
        self,
        expr: Any,
        fn: Any,
        params: dict[str, int],
        locals_: dict[str, frozenset[int]],
        transfers: list[Any],
        count: list[int],
    ) -> frozenset[int]:
        """One `return` expression's deps. A bound closure name re-
        resolves its captured bindings at the return — a captured local
        reassigned between the literal and the `return cl` reads the
        CURRENT value (`y = x` after `cl := func(){return y}` hands x's
        deps to the caller, not the empty set the literal captured)."""
        deps = self.expression(
            expr, fn, params, locals_, transfers, count, 0
        )
        idents = [expr] if expr.type == "identifier" else []
        if not idents and expr.type == "composite_literal":
            # `return []func(){cl}` — a closure returned as a
            # collection element re-resolves its captures the
            # same way a bare `return cl` does.
            value = expr.child_by_field_name("body") or next(
                (c for c in expr.named_children
                 if c.type == "literal_value"),
                None,
            )
            idents = [
                inner
                for c in (value.named_children if value else ())
                for inner in (
                    [c] if c.type == "identifier"
                    else (c.named_children if c.type in
                          ("literal_element", "keyed_element") else ())
                )
                if inner.type == "identifier"
            ]
        for ident in idents:
            ref = self.references.get(self.node_key(ident))
            if ref is not None and ref.binding_id:
                extra = self._captured_current_deps(
                    self.closure_captures.get(
                        ref.binding_id, frozenset()
                    ),
                    params,
                    locals_,
                )
                deps |= extra
                self._record_read(extra)
        return deps

    def _func_result_chan_args(
        self,
        rhs_node: Any,
        locals_: dict[str, frozenset[int]],
        params: dict[str, int],
    ) -> frozenset[int]:
        """`f := mk(ch)` — a call bound under a `func`-typed name
        may return a closure capturing the queue it received, so
        the arg's queue joins the external model like a `chan`
        argument to an interface call does: a later `ch <- x`
        broadcasts into `indirect_writes`, which the opaque `f()`
        call then observes. Non-call RHS nodes promote nothing."""
        if rhs_node is not None and self._elem_call_conversion(
            rhs_node
        ):
            # `f := fs[i](ch)` — the conversion-form element call
            # promotes the chan argument's queue the same way: the
            # returned closure may capture it.
            return self._promote_chan_call_args(
                rhs_node, "", locals_, params
            )
        if (
            rhs_node is not None
            and rhs_node.type == "call_expression"
        ):
            deps = self._promote_chan_call_args(
                rhs_node, "", locals_, params
            )
            # `c.Mk()…` — a chan-typed receiver shares its queue
            # with the produced closure just like a `chan`
            # argument does, so promote it alongside the args.
            callee = rhs_node.child_by_field_name("function")
            if (
                callee is not None
                and callee.type == "selector_expression"
            ):
                operand = callee.child_by_field_name("operand")
                if operand is not None:
                    deps |= self._promote_chan_arg_roots(
                        (operand,), "", locals_, params
                    )
            return deps
        return frozenset()

    def _chan_result_call(self, node: Any, fact_pred: Any = None) -> Any:
        """The callee `node` calls when `ch := f()` binds a
        callee-produced queue — `f` declares one scalar-element
        `chan` result. A local callee's function record carries the
        result's fact directly; an imported member declares its
        `result_types` facts so `lib.G()` admits the same way."""
        pred = fact_pred or self._scalar_chan_fact
        inner = node
        while (
            inner is not None
            and inner.type == "parenthesized_expression"
        ):
            inner = next(
                (c for c in inner.named_children if c.type != "comment"),
                None,
            )
        if inner is None or inner.type != "call_expression":
            return None
        call = self.calls.get(self.node_key(inner))
        if call is None:
            return None
        if call.kind == "direct_local":
            target = self.functions.get(call.target)
            if (
                target is None
                or len(target.results) != 1
                or not pred(target.results[0].type)
            ):
                return None
            return target
        if call.kind == "direct_import":
            member = self.members.get(call.target)
            if (
                member is None
                or len(member.result_types) != 1
                or not pred(member.result_types[0])
            ):
                return None
            return member
        return None

    def _func_iterator_result(self, node: Any) -> bool:
        """`node` is a call whose result is func-typed — the operand
        of `for v := range g()` when g yields a `func(yield)`
        iterator. A local callee's function record declares the
        result's fact; an imported member's `result_types` carry it.
        """
        call = self.calls.get(self.node_key(node))
        if call is None:
            return False
        if call.kind == "direct_local":
            target = self.functions.get(call.target)
            return (
                target is not None
                and len(target.results) == 1
                and target.results[0].type.kind == "function"
            )
        if call.kind == "direct_import":
            member = self.members.get(call.target)
            return (
                member is not None
                and len(member.result_types) == 1
                and member.result_types[0].kind == "function"
            )
        return False

    def _imported_chan_result_args(
        self, node: Any, locals_: dict, params: dict, index: int = 0
    ) -> tuple:
        """The channel arguments of an imported `ch := lib.G(...)`
        call — every `chan` argument's resolved root binding.

        The imported callee's body is opaque: `lib.G(q)` may hand
        the caller's own queue back (`return q`), so each channel
        argument must join the external model — the result may
        literally be that queue. `index` is the bound result slot —
        a multi-result callee admits at the slot declaring the
        scalar `chan` (`ch, n := lib.G(q)`). A method call
        `q.M()` promotes the receiver the same way: the opaque
        body may `return c` its own channel receiver, so `ch :=
        q.M()` binds a queue `q` itself still names — sends
        through `ch` must reach reads on `q`."""
        inner = node
        while (
            inner is not None
            and inner.type == "parenthesized_expression"
        ):
            inner = next(
                (c for c in inner.named_children if c.type != "comment"),
                None,
            )
        if inner is None or inner.type != "call_expression":
            return ()
        call = self.calls.get(self.node_key(inner))
        if call is None or call.kind != "direct_import":
            return ()
        member = self.members.get(call.target)
        if (
            member is None
            or index >= len(member.result_types)
            or not self._scalar_chan_fact(member.result_types[index])
        ):
            return ()
        arg_list = next(
            (
                c
                for c in inner.named_children
                if c.type == "argument_list"
            ),
            None,
        )
        if arg_list is None:
            return ()
        roots = []
        for arg in arg_list.named_children:
            if arg.type == "comment":
                continue
            while arg.type == "parenthesized_expression":
                arg = next(
                    (
                        c
                        for c in arg.named_children
                        if c.type != "comment"
                    ),
                    None,
                )
                if arg is None:
                    break
            if arg is None or arg.type != "identifier":
                continue
            chan = self._chan_binding(arg, locals_, params)
            if chan is not None:
                roots.append(self._chan_root(chan.id))
        if call.method:
            # `q.M()` — the receiver sits outside the argument
            # list, and the opaque body may hand it straight back
            # (`return c`), so promote its root like an argument.
            callee = next(
                (
                    c
                    for c in inner.named_children
                    if c.type == "selector_expression"
                ),
                None,
            )
            operand = (
                callee.child_by_field_name("operand")
                if callee is not None
                else None
            )
            if operand is not None and operand.type == "identifier":
                chan = self._chan_binding(operand, locals_, params)
                if chan is not None:
                    root = self._chan_root(chan.id)
                    if root not in roots:
                        roots.append(root)
        return tuple(roots)

    def _chan_result_call_at(
        self, node: Any, index: int, fact_pred: Any = None
    ) -> Any:
        """`node` calls a local callee declaring a scalar `chan` in
        result slot `index` — a multi-result callee's `ch` position
        (`ch, n := g()` where `g` returns `(chan T, int64)`).
        Returns the callee's Function record or None. Each slot's
        LHS resolves against the same call node, so only the
        per-position result type decides admission."""
        inner = node
        while (
            inner is not None
            and inner.type == "parenthesized_expression"
        ):
            inner = next(
                (c for c in inner.named_children if c.type != "comment"),
                None,
            )
        if inner is None or inner.type != "call_expression":
            return None
        call = self.calls.get(self.node_key(inner))
        if call is None:
            return None
        pred = fact_pred or self._scalar_chan_fact
        if call.kind == "direct_local":
            target = self.functions.get(call.target)
            if (
                target is None
                or index >= len(target.results)
                or not pred(
                    target.results[index].type
                )
            ):
                return None
            return target
        if call.kind == "direct_import":
            member = self.members.get(call.target)
            if (
                member is None
                or index >= len(member.result_types)
                or not pred(
                    member.result_types[index]
                )
            ):
                return None
            return member
        return None

    def _call_result_type(self, node: Any) -> Any | None:
        """The declared type fact of a call's single result — for
        `direct_local`/`method`-style callees the Function record's
        `results[0].type`, for `direct_import` the member's
        `result_types[0]`. None for other kinds or multi-result
        calls, whose per-slot types need an index."""
        inner = node
        while (
            inner is not None
            and inner.type == "parenthesized_expression"
        ):
            inner = next(
                (c for c in inner.named_children if c.type != "comment"),
                None,
            )
        if inner is None or inner.type not in (
            "call_expression",
            # `fs[k](x)` — the index-call shape parses as a
            # generic-instantiation conversion but records a call.
            "type_conversion_expression",
        ):
            return None
        call = self.calls.get(self.node_key(inner))
        if call is None:
            return None
        if call.kind == "direct_import":
            member = self.members.get(call.target)
            if member is not None and member.result_types:
                return member.result_types[0]
            return None
        target = self.functions.get(call.target)
        if target is not None and len(target.results) == 1:
            return target.results[0].type
        return None

    def _struct_literal_field_names(self, literal: Any) -> frozenset[str]:
        """The DIRECT field names a `struct{...}` literal declares —
        identifiers of each `field_declaration`'s `name`, plus the
        embedded type's trailing identifier (`*Q` / `lib.Q` name Q).
        Nested literals' inner fields are not direct, so name-matching
        a unified resolution against this set cannot admit a promoted
        field (`struct{ A struct{ V int64 }; *Q }` resolves `s.V` to
        Q's V — `V` is not a direct name here)."""
        names: set[str] = set()
        decls = [
            c
            for c in literal.named_children
            if c.type == "field_declaration_list"
        ]
        children = (
            decls[0].named_children
            if decls
            else literal.named_children
        )
        for child in children:
            if child.type != "field_declaration":
                continue
            declared = [
                c.text.decode()
                for c in child.named_children
                if c.type == "field_identifier"
            ]
            if declared:
                names.update(declared)
                continue
            type_node = child.child_by_field_name("type")
            # Embedded fields carry TYPE names — `type_identifier`
            # (`*Q`, `Q`), or a `qualified_type`'s trailing one
            # (`lib.Q` — `package_identifier` never qualifies).
            pool = [type_node] if type_node is not None else []
            while pool:
                current = pool.pop()
                if current.type in {"identifier", "type_identifier"}:
                    names.add(current.text.decode())
                    break
                pool.extend(reversed(current.named_children))
        return frozenset(names)

    def _call_result_struct_literal(
        self, node: Any, result_index: int = 0
    ) -> Any | None:
        """(literal, file) for the `struct{...}` literal a `:=`/`var`
        RHS binds — a composite literal's own `type` child, or the
        result signature literal of a direct local call's anonymous-
        struct result at `result_index` (`_, s := G()` picks slot 1).
        The signature literal lives in the callee's file; a composite
        literal in the current one."""
        inner = node
        while (
            inner is not None
            and inner.type == "parenthesized_expression"
        ):
            inner = next(
                (c for c in inner.named_children if c.type != "comment"),
                None,
            )
        if inner is None:
            return None
        if inner.type == "composite_literal":
            literal = inner.child_by_field_name("type")
            return (
                (literal, self.current_file)
                if literal is not None and literal.type == "struct_type"
                else None
            )
        if inner.type != "call_expression":
            return None
        call = self.calls.get(self.node_key(inner))
        if call is None or call.kind != "direct_local":
            return None
        target = self.functions.get(call.target)
        if (
            target is None
            or len(target.results) <= result_index
            or target.results[result_index].type.kind != "struct"
            or target.results[result_index].type.type_id
        ):
            return None
        fn_binding = self.bindings.get(target.binding_id)
        block = (
            self.blocks.get(_key3(fn_binding.span))
            if fn_binding is not None
            else None
        )
        decl = block.parent if block is not None else None
        result_node = (
            decl.child_by_field_name("result")
            if decl is not None
            else None
        )
        if result_node is None:
            return None
        if result_node.type == "struct_type":
            literal = result_node
        else:
            # `func G() (struct{...})` — a parenthesized result list
            # with one declaration whose type child is the literal.
            decls = [
                c
                for c in result_node.named_children
                if c.type == "parameter_declaration"
            ]
            # `(a int64, s struct{ V int64 })` — slot i's type lives on
            # the declaration that covers it; a declaration spans one
            # result per name, or exactly one when it carries none.
            literal = None
            slot = result_index
            for param_decl in decls:
                width = (
                    sum(
                        1
                        for c in param_decl.named_children
                        if c.type == "identifier"
                    )
                    or 1
                )
                if slot < width:
                    literal = param_decl.child_by_field_name("type")
                    break
                slot -= width
        if literal is None or literal.type != "struct_type":
            return None
        file = (
            fn_binding.span.file
            if isinstance(fn_binding.span, FileSpan)
            else 0
        )
        return (literal, file)

    def _call_result_struct_anchor(self, node: Any) -> Any | None:
        """The anchor for a direct local call's single anonymous-struct
        result — `p := G(x)` where G is `func G(...) struct{ V int64 }`
        declares V inside G's signature, not after p's name, so p's
        field window anchors at the literal's own start. A composite
        literal RHS (`p = struct{...}{...}`) anchors the same way."""
        result = self._call_result_struct_literal(node)
        if result is None:
            return None
        literal, file = result
        return FileSpan(file, literal.start_byte, literal.start_byte)

    def _record_sig_struct_anchors(
        self, decl: Any, file: int
    ) -> None:
        """`func F(s, t struct{ V int64 }) (r struct{ W int64 })` —
        an anonymous-struct parameter or named result declares its
        fields inside the signature's literal, which sits after the
        LAST name in the declaration (or inside the result list), so
        each binding's field window anchors at the literal's own
        start, not the binding's name span."""
        if decl is None:
            return
        for field in ("parameters", "result"):
            lst = decl.child_by_field_name(field)
            if lst is None or lst.type != "parameter_list":
                continue
            for param_decl in lst.named_children:
                if param_decl.type != "parameter_declaration":
                    continue
                literal = param_decl.child_by_field_name("type")
                if literal is None or literal.type != "struct_type":
                    continue
                anchor = FileSpan(
                    file, literal.start_byte, literal.start_byte
                )
                names_set = self._struct_literal_field_names(literal)
                for name in param_decl.named_children:
                    if name.type != "identifier":
                        continue
                    binding = self.bindings_by_span.get(
                        (file, name.start_byte, name.end_byte)
                    )
                    if binding is not None:
                        self.anon_struct_anchor[binding.id] = anchor
                        self.anon_struct_field_names[binding.id] = (
                            names_set
                        )

    def _chan_result_passthrough(
        self,
        node: Any,
        locals_: dict[str, frozenset[int]],
        params: dict[str, int],
        index: int = 0,
    ) -> Any | None:
        """`c := g(q)` where `g`'s whole body is `return <param>` —
        the bound name aliases the argument's queue (the callee hands
        the same queue back), so it binds through `chan_aliases`
        rather than the external-local model. `index` picks the
        result slot for a multi-result callee (`c, n := g(q)` checks
        `return q, 0` at slot 0). Returns the alias source binding,
        or None when the callee is not a pure passthrough or the
        passed-through argument is not a channel identifier."""
        inner = node
        while (
            inner is not None
            and inner.type == "parenthesized_expression"
        ):
            inner = next(
                (c for c in inner.named_children if c.type != "comment"),
                None,
            )
        if inner is None or inner.type != "call_expression":
            return None
        call = self.calls.get(self.node_key(inner))
        if call is None or call.kind != "direct_local":
            return None
        target = self.functions.get(call.target)
        if target is None:
            return None
        fn_binding = self.bindings.get(target.binding_id)
        block = (
            self.blocks.get(_key3(fn_binding.span))
            if fn_binding is not None
            else None
        )
        if block is None:
            return None
        stmts = [c for c in block.named_children if c.type != "comment"]
        while len(stmts) == 1 and stmts[0].type == "statement_list":
            stmts = [
                c
                for c in stmts[0].named_children
                if c.type != "comment"
            ]
        if len(stmts) != 1 or stmts[0].type != "return_statement":
            return None
        expr = next(
            (
                c
                for c in stmts[0].named_children
                if c.type != "comment"
            ),
            None,
        )
        if expr is not None and expr.type == "expression_list":
            items = [
                c for c in expr.named_children if c.type != "comment"
            ]
            expr = items[index] if index < len(items) else None
        elif index != 0:
            return None
        if expr is None or expr.type != "identifier":
            return None
        ref = self.references.get(self.node_key(expr))
        if ref is None:
            return None
        param_index = next(
            (
                i
                for i, p in enumerate(target.parameters)
                if p.binding_id == ref.binding_id
            ),
            None,
        )
        if param_index is None:
            return None
        args = inner.child_by_field_name("arguments")
        arg_nodes = (
            [
                c
                for c in args.named_children
                if c.type != "comment"
            ]
            if args is not None
            else []
        )
        if call.method_expr:
            # `S.Pick(s, a, b)` — argument 0 is the receiver, so the
            # callee's declared parameter `param_index` sits one slot
            # later.
            param_index += 1
        if param_index >= len(arg_nodes):
            return None
        return self._chan_alias_target(
            arg_nodes[param_index], locals_, params
        )

    def _is_make_chan_call(self, node: Any) -> bool:
        """`make(chan T[, cap])` — the one in-fragment channel
        constructor. Anything else on the RHS of a channel binding
        (an identifier copy, a receive, a call result) aliases or
        produces a queue the conflated dep set cannot model."""
        if node is None or node.type != "call_expression":
            return False
        call = self.calls.get(self.node_key(node))
        if call is None or call.kind != "builtin":
            return False
        function_node = node.child_by_field_name("function")
        while (
            function_node is not None
            and function_node.type == "parenthesized_expression"
        ):
            function_node = next(
                iter(function_node.named_children), None
            )
        if function_node is None or function_node.text != b"make":
            return False
        arguments_node = node.child_by_field_name("arguments")
        arguments = (
            _children(arguments_node) if arguments_node is not None else []
        )
        return (
            arguments
            and arguments[0].type == "channel_type"
        )

    def _func_elem_make(self, node: Any) -> bool:
        """`make(<coll>[, n])` — a fresh EMPTY func-element
        container: `make([]func, n)`/`make(map[K]func)` binds the
        same way `fs := []func(){}` does — zero elements, an empty
        dep set, and the bind gates admit on the declared collection
        type. A named collection type (`make(FM, n)`) resolves
        through its declared fact; `make(chan T)` stays on the
        channel path."""
        if node is None or node.type != "call_expression":
            return False
        call = self.calls.get(self.node_key(node))
        if call is None or call.kind != "builtin":
            return False
        function_node = node.child_by_field_name("function")
        while (
            function_node is not None
            and function_node.type == "parenthesized_expression"
        ):
            function_node = next(
                iter(function_node.named_children), None
            )
        if function_node is None or function_node.text != b"make":
            return False
        arguments_node = node.child_by_field_name("arguments")
        arguments = (
            _children(arguments_node) if arguments_node is not None else []
        )
        if not arguments or len(arguments) > 3:
            return False
        type_arg = arguments[0]
        while (
            type_arg is not None and type_arg.type == "parenthesized_type"
        ):
            type_arg = next(iter(type_arg.named_children), None)
        if type_arg is None:
            return False
        if type_arg.type in {"slice_type", "array_type"}:
            return self._func_elem_type_node(
                type_arg.child_by_field_name("element")
            )
        if type_arg.type == "map_type":
            return self._func_elem_type_node(
                type_arg.child_by_field_name("value")
            )
        if type_arg.type == "type_identifier":
            ref = self.references.get(self.node_key(type_arg))
            binding = (
                self.bindings.get(ref.binding_id)
                if ref is not None and ref.binding_id
                else None
            )
            return (
                binding is not None
                and binding.kind == "type"
                and (
                    self._func_elem_collection(binding.type)
                    or self._func_elem_nested_collection(binding.type)
                )
            )
        return False

    def _func_elem_type_node(
        self, node: Any, depth: int = 0
    ) -> bool:
        """A type expression whose element resolves to a function
        type at one level — the `func` type itself, or a
        slice/array/map whose element (or map value) is a func
        element type. One extra collection level is the deepest the
        model conflates, so `[][][]func` stays closed. A named
        element type resolves through its declared fact."""
        while (
            node is not None and node.type == "parenthesized_type"
        ):
            node = next(iter(node.named_children), None)
        if node is None:
            return False
        if node.type == "function_type":
            return True
        if depth >= 1:
            return False
        if node.type in {"slice_type", "array_type"}:
            return self._func_elem_type_node(
                node.child_by_field_name("element"), depth + 1
            )
        if node.type == "map_type":
            return self._func_elem_type_node(
                node.child_by_field_name("value"), depth + 1
            )
        if node.type == "type_identifier":
            ref = self.references.get(self.node_key(node))
            binding = (
                self.bindings.get(ref.binding_id)
                if ref is not None and ref.binding_id
                else None
            )
            return (
                binding is not None
                and binding.kind == "type"
                and (
                    self._func_elem_collection(binding.type)
                    or self._func_elem_nested_collection(binding.type)
                )
            )
        return False

    def _pin_func_elem_make_type(self, node: Any) -> bool:
        """Pin the named identities a func-element `make` type
        expression names. `_pin_type_node` rejects signature
        literals outright, so the collection's non-signature
        children pin through it while the func element's own
        parameter/result types walk their names instead."""
        while (
            node is not None and node.type == "parenthesized_type"
        ):
            node = next(iter(node.named_children), None)
        if node is None:
            return False
        if node.type == "type_identifier":
            return self._pin_type_node(node)
        if node.type in {"slice_type", "array_type"}:
            return self._pin_func_elem_type_node(
                node.child_by_field_name("element")
            )
        if node.type == "map_type":
            key = node.child_by_field_name("key")
            value = node.child_by_field_name("value")
            return self._pin_type_node(
                key
            ) and self._pin_func_elem_type_node(value)
        return False

    def _pin_func_elem_type_node(
        self, node: Any, depth: int = 0
    ) -> bool:
        """Pin the named identities under a func-element `make`
        type, mirroring `_func_elem_type_node`'s one-extra-level
        walk: a func element's signature names pin through
        `_pin_signature_type`; a named element pins through its
        `type` binding; a map's key pins as a plain type."""
        while (
            node is not None and node.type == "parenthesized_type"
        ):
            node = next(iter(node.named_children), None)
        if node is None:
            return False
        if node.type == "function_type":
            return self._pin_signature_type(node)
        if depth >= 1:
            return False
        if node.type == "type_identifier":
            return self._pin_type_node(node)
        if node.type in {"slice_type", "array_type"}:
            return self._pin_func_elem_type_node(
                node.child_by_field_name("element"), depth + 1
            )
        if node.type == "map_type":
            key = node.child_by_field_name("key")
            value = node.child_by_field_name("value")
            return self._pin_type_node(key) and (
                self._pin_func_elem_type_node(value, depth + 1)
            )
        return False

    def _pin_signature_type(self, node: Any) -> bool:
        """Pin every named identity a `func` type literal's
        parameter and result types name."""
        if node is None or node.type != "function_type":
            return False
        ok = True
        params = node.child_by_field_name("parameters")
        if params is not None:
            for decl in params.named_children:
                typed = decl.child_by_field_name("type")
                if typed is not None and not self._pin_type_node(
                    typed
                ):
                    ok = False
        result = node.child_by_field_name("result")
        if result is not None and not self._pin_type_node(result):
            ok = False
        return ok

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
        eval_extras: bool = True,
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
        if eval_extras:
            self._eval_write_extras(
                extras, fn, params, locals_, transfers, count
            )

    def _eval_write_extras(
        self,
        extras: tuple[Any, ...],
        fn: Any,
        params: dict[str, int],
        locals_: dict[str, frozenset[int]],
        transfers: list[CallTransfer],
        count: list[int],
    ) -> None:
        # Extras were collected outermost-first while descending the
        # operand chain; Go evaluates indices inside-out — the inner
        # index of `lib.V2[f()][g()]` runs before `g()` — so a write
        # `f()` performs must already be visible when `g()`'s call
        # arguments record their dependencies.
        for extra in reversed(extras):
            # The write reads its index operands like the read side
            # does: every non-literal extra evaluates through the
            # normal expression gate — unmodelled shapes stay closed —
            # and its dependencies attribute to the statement. Calls
            # and member reads inside record their transfers and pins
            # that `stale_dependents` later reads.
            if extra.type in _INDEX_LITERALS:
                continue
            self._record_read(
                self.expression(
                    extra, fn, params, locals_, transfers, count, 0
                )
            )

    def _record_package_write(
        self,
        lhs: Any,
        binding: Any,
        extras: tuple[Any, ...],
        fn: Function,
        params: dict[str, int],
        locals_: dict[str, frozenset[int]],
        transfers: list[CallTransfer],
        count: list[int],
        eval_extras: bool = True,
    ) -> None:
        """Record a package-level `var` write's mutation + index calls.

        Package state is external like an imported member's: the
        var's own binding identity is the transfer target — a real
        identity in `known`, so redeclaring it flags
        `stale_dependents` in both directions — and every named
        identity inside its declared type pins.
        """
        if binding.type is not None:
            self._pin_fact_identities(binding.type)
        transfers.append(
            CallTransfer(
                FileSpan(self.current_file, lhs.start_byte, lhs.end_byte),
                binding.id,
                (),
                frozenset(),
                imported=True,
            )
        )
        if eval_extras:
            # Same rule as `_record_member_write`: indices evaluate
            # inside-out, literals skip, and the read's dependencies
            # attribute to the statement.
            self._eval_write_extras(
                extras, fn, params, locals_, transfers, count
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
                # Synthetic `<binding>/pointee` ids name an unnamed
                # pointee no declaration can redeclare — pinning one
                # would flag the summary stale forever.
                self.pinned.update(
                    p.id
                    for p in pointees
                    if not p.id.endswith("/pointee")
                )
                # A nested selection (`t.W.f`) traverses a stored
                # pointer field — the caller marks the target so the
                # destination read unions the indirect stores where
                # earlier `t.W = q` folds landed.
                return pointees[-1].id, ref, True
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
            return "", ref, True
        if base is None or base.type != "identifier" or base.text == b"_":
            return None
        ref = self.references.get(self.node_key(base))
        if ref is None or (
            ref.binding_id not in locals_ and ref.binding_id not in params
        ):
            return None
        binding = self.bindings.get(ref.binding_id)
        if binding is None:
            return None
        if not binding.type.type_id and binding.type.kind != "struct":
            # `t.V = v` on a bound `*struct{...}` — the anonymous
            # pointee names no `type` identity, but the store still
            # lands in caller memory the dep model never tracks:
            # the synthetic `<binding>/pointee` identity records it
            # like every other unnamed pointee's.
            elem = binding.type.elem
            if (
                binding.type.kind != "pointer"
                or elem is None
                or elem.kind != "struct"
            ):
                return None
            return ref.binding_id + "/pointee", ref, False
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
            return "", ref, False
        if binding.type.kind != "pointer":
            return None
        return binding.type.type_id, ref, False

    def _bound_container_pointee(
        self,
        node: Any,
        locals_: dict[str, frozenset[int]],
        params: dict[str, int],
    ) -> tuple[Any, str, Any] | None:
        """A bound pointer whose pointee is a container — `p *[]T`,
        `p *map[K]V`, `p *[N]T`, or a named `p *S` resolving to one.

        Returns (reference, pointee identity, container fact) or
        None. The identity is the named pointee's `type_id`, or the
        per-binding synthetic `<binding_id>/pointee` for an unnamed
        `*[]T`-shaped pointer — the same classification
        `_bound_pointer_write` uses for scalars, so the synthetic id
        can never be redeclared nor falsely flag `stale_dependents`.
        A bound pointer can never point at a local composite (the
        `&` gate closes `&s`/`&st`), which is what makes the
        external-state treatment sound.
        """
        ref = self.references.get(self.node_key(node))
        if ref is None or (
            ref.binding_id not in locals_ and ref.binding_id not in params
        ):
            return None
        binding = self.bindings.get(ref.binding_id)
        if binding is None or binding.type.kind != "pointer":
            return None
        if binding.type.type_id:
            target = self._pointee_type(binding.type.type_id)
            if target is None:
                return None
            if target.type.kind == "pointer":
                # `type PP *[]T` — the declared type names the
                # pointer itself; the container pointee is its
                # `elem`, pinned with PP's whole fact.
                self._pin_fact_identities(target.type)
                elem = target.type.elem
                if elem is None or elem.kind not in {
                    "slice",
                    "array",
                    "map",
                }:
                    return None
                return (
                    ref,
                    elem.type_id or f"{ref.binding_id}/pointee",
                    elem,
                )
            if target.type.kind not in {"slice", "array", "map"}:
                return None
            return ref, binding.type.type_id, target.type
        elem = binding.type.elem
        if elem is None or elem.kind not in {"slice", "array", "map"}:
            return None
        return ref, f"{ref.binding_id}/pointee", elem

    def _pointer_underlying_pointee(
        self, member: PackageMember, owner_id: str
    ) -> Any | None:
        """The pointee a `type PP *T` member's `elem` names — the
        named pointee's `type` member, or an anonymous
        `*struct{...}` pointee under `owner_id`'s `/pointee`
        identity (which can never redeclare, so it flags no false
        staleness). An unnamed pointee with no modelled shape
        (`*int64` on a basic type, or a missing elem) stays
        closed."""
        elem = member.type.elem
        if elem is None:
            return None
        if elem.type_id:
            return self._pointee_type(elem.type_id)
        if elem.kind == "struct":
            return _AnonymousPointee(owner_id + "/pointee", elem)
        return None

    def _package_container_pointee(
        self, node: Any
    ) -> tuple[str, Any] | None:
        """`(*GP)[i]` — a package-level pointer var whose pointee is
        a container, for an index chain's root. Returns (the var's
        own binding identity, the pointee's container fact) or
        None — the var's id records the read like `GA[i]` records
        the container var's."""
        ref = self.references.get(self.node_key(node))
        binding = (
            self.bindings.get(ref.binding_id)
            if ref is not None and ref.binding_id
            else None
        )
        if (
            binding is None
            or binding.kind != "variable"
            or not self._package_level(binding)
            or binding.type.kind != "pointer"
        ):
            return None
        elem = binding.type.elem
        if elem is None or elem.kind not in {"slice", "array", "map"}:
            return None
        return binding.id, elem

    def _bound_container_write(
        self,
        node: Any,
        locals_: dict[str, frozenset[int]],
        params: dict[str, int],
    ) -> tuple[str, tuple[Any, ...], Any] | None:
        """`(*p)[i] = v` / `p[i] = v` — an index-element store
        through a bound pointer whose pointee is a container.

        Returns (pointee identity, index nodes outermost-first,
        innermost container fact, the bound root's reference) or
        None. The element the last level writes must be
        scalar-or-pointer, like the read side.
        """
        cur = node
        while cur is not None and cur.type == "parenthesized_expression":
            cur = next(
                (c for c in cur.named_children if c.type != "comment"),
                None,
            )
        if cur is None or cur.type != "index_expression":
            return None
        extras: list[Any] = []
        inner = cur
        while inner is not None and inner.type == "index_expression":
            idx = inner.child_by_field_name("index")
            if idx is not None:
                extras.append(idx)
            inner = inner.child_by_field_name("operand")
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
        ident = None
        if inner is not None and inner.type == "unary_expression":
            operator = inner.child_by_field_name("operator")
            sub = inner.child_by_field_name("operand")
            while (
                sub is not None
                and sub.type == "parenthesized_expression"
            ):
                sub = next(
                    (
                        c
                        for c in sub.named_children
                        if c.type != "comment"
                    ),
                    None,
                )
            if (
                operator is not None
                and operator.text == b"*"
                and sub is not None
                and sub.type == "identifier"
            ):
                ident = sub
        elif inner is not None and inner.type == "identifier":
            # `p[i]` on `p *[N]T` — Go's auto-deref sugar for
            # pointer-to-array indexing.
            ident = inner
        if ident is None:
            return None
        bound = self._bound_container_pointee(ident, locals_, params)
        if bound is None:
            return None
        _, pointee_id, fact = bound
        container_kinds = {"slice", "array", "map"}
        for _ in range(len(extras) - 1):
            if (
                fact is None
                or fact.kind not in container_kinds
                or fact.elem is None
            ):
                return None
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
            elem is None
            or elem.kind not in {"integer", "boolean", "pointer"}
        ):
            return None
        return pointee_id, tuple(extras), fact, bound[0]

    def _bound_pointer_write(
        self,
        node: Any,
        locals_: dict[str, frozenset[int]],
        params: dict[str, int],
    ) -> tuple[str, Any, int] | None:
        """A `*p = v`/`**pp = v`/`***t = v` store through a bound
        pointer.

        `p := &x` may aim the pointer at any escaped binding — dep
        sets track binding indices, never pointee contents, so the
        store cannot be proven to miss tracked state. It admits only
        through the escaped-binding fold (the `_ALIAS_FOLD` sentinel
        the caller installs): unioning the stored value's deps into
        every escaped binding is the same over-approximation
        `*lib.PV = v` uses. Returns the declared pointee identity
        for the mutation's transfer record — or None when the LHS is
        not a bound-pointer dereference or the binding's pointer
        names no pointee at all (a fact recorded before `elem` was
        emitted, or an unresolvable `type_id`). The fold is
        unconditional, so any resolvable pointee admits — composite
        shapes included; the READ side's scalar-or-pointer
        classification does not apply to stores.
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
        # `*p`, `**pp`, `***t` — each unary `*` operand unwraps one
        # more deref level (through parens) until the chain ends at
        # the bound identifier. `extra` counts the levels past the
        # outermost `*`; a non-identifier operand at any depth
        # (`*(*g())`, `**s.F`) closes below.
        extra = 0
        while inner is not None and inner.type == "unary_expression":
            inner_op = inner.child_by_field_name("operator")
            inner_operand = inner.child_by_field_name("operand")
            while (
                inner_operand is not None
                and inner_operand.type == "parenthesized_expression"
            ):
                inner_operand = next(
                    (
                        c
                        for c in inner_operand.named_children
                        if c.type != "comment"
                    ),
                    None,
                )
            if (
                inner_op is None
                or inner_op.text != b"*"
                or inner_operand is None
            ):
                break
            inner = inner_operand
            extra += 1
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
            # own `elem` carries its kind. Any emitted `elem` admits
            # on the write side: the store lands in external memory
            # and folds unconditionally, so composite pointees
            # (`*[]int64`, `*struct{...}`) are as sound as scalars —
            # only a fact recorded before `elem` was emitted stays
            # closed. The returned identity is per-binding — nothing
            # declared can ever redeclare it, so `stale_dependents`
            # can never falsely flag it.
            pointee_fact = binding.type.elem
            if pointee_fact is None:
                return None
            # The pointee's element type can name declared
            # identities (`*[]lib.T`) that the synthetic
            # `/pointee` target cannot carry — pin them so a
            # redeclaration flags `stale_dependents`.
            self._pin_fact_identities(pointee_fact)
            pointee_id = f"{ref.binding_id}/pointee"
        else:
            target = self._pointee_type(binding.type.type_id)
            if target is None:
                return None
            # Same pin on the named pointee's resolved fact — its
            # element/key `type_id`s (`type S = []lib.T`) ride under
            # the `type_id` the transfer records.
            self._pin_fact_identities(target.type)
            pointee_fact = target.type
            pointee_id = binding.type.type_id
        if extra:
            # `**pp = v`, `***t = v` — the store lands `extra`
            # levels deeper than the first pointee; descend the
            # fact chain that many levels under the same
            # unconditional fold. Each intermediate level must be
            # pointer-kind (an opaque named pointer or a scalar
            # stops the chain); the deepest `elem` is the stored
            # value's type.
            cur = pointee_fact
            for _ in range(extra - 1):
                if cur.kind != "pointer" or cur.elem is None:
                    return None
                cur = cur.elem
                self._pin_fact_identities(cur)
            if cur.kind != "pointer":
                return None
            deep = cur.elem
            if deep is None:
                return None
            self._pin_fact_identities(deep)
            if deep.type_id:
                return deep.type_id, ref, extra
            return (
                f"{ref.binding_id}" + "/pointee" * (extra + 1),
                ref,
                extra,
            )
        return pointee_id, ref, extra

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
            # (`*g()`) stays closed. A nested `**t`/`***t` unwraps
            # one more level each: the innermost operand must still
            # be a bare identifier and the bound name's pointee
            # chain must resolve pointer → … → scalar/pointer.
            extra = 0
            while inner is not None and inner.type == "unary_expression":
                inner_op = inner.child_by_field_name("operator")
                inner_operand = inner.child_by_field_name("operand")
                while (
                    inner_operand is not None
                    and inner_operand.type == "parenthesized_expression"
                ):
                    inner_operand = next(
                        (
                            c
                            for c in inner_operand.named_children
                            if c.type != "comment"
                        ),
                        None,
                    )
                if (
                    inner_op is None
                    or inner_op.text != b"*"
                    or inner_operand is None
                ):
                    break
                inner = inner_operand
                extra += 1
            if inner is None or inner.type != "identifier":
                raise _Unsupported("non_parameter_reference", _span(node))
            bound_ref = self.references.get(self.node_key(inner))
            binding = (
                self.bindings.get(bound_ref.binding_id)
                if bound_ref is not None and bound_ref.binding_id
                else None
            )
            if bound_ref is None or (
                bound_ref.binding_id not in locals_
                and bound_ref.binding_id not in params
                and not (
                    binding is not None
                    and binding.kind == "variable"
                    and self._package_level(binding)
                )
            ):
                raise _Unsupported("non_parameter_reference", _span(node))
            # `*GP` on a package-level pointer var reads through
            # package state into memory the model does not track —
            # the same external read `*p` is.
            if binding is None or binding.type.kind != "pointer":
                raise _Unsupported("non_parameter_reference", _span(node))
            if extra:
                # `**pp`, `***t` — descend the fact chain `extra`
                # levels past the pointer's own type: every level
                # must resolve to another pointer whose own element
                # continues the chain, and the deepest element
                # classifies scalar or pointer like a first-level
                # pointee would. A named step (`type PP *int64`)
                # resolves through the type binding and pins it; an
                # unnamed inner `*T` records a
                # `<binding>/pointee…` identity nothing can
                # redeclare.
                inner_fact = binding.type
                for _ in range(extra):
                    if inner_fact.type_id:
                        resolved = self._pointee_type(
                            inner_fact.type_id
                        )
                        if (
                            resolved is None
                            or resolved.type.kind != "pointer"
                        ):
                            raise _Unsupported(
                                "non_parameter_reference", _span(node)
                            )
                        self._pin_fact_identities(resolved.type)
                        inner_fact = resolved.type
                    else:
                        inner_fact = inner_fact.elem
                        if (
                            inner_fact is None
                            or inner_fact.kind != "pointer"
                        ):
                            raise _Unsupported(
                                "non_parameter_reference", _span(node)
                            )
                        self._pin_fact_identities(inner_fact)
                deep = inner_fact.elem
                if (
                    deep is None
                    or deep.kind
                    not in {"integer", "boolean", "pointer"}
                ):
                    raise _Unsupported(
                        "non_parameter_reference", _span(node)
                    )
                # `deep`'s own `type_id` names ITS pointee (`*S`
                # carries `S`), not a type this read returns — the
                # pointer-kind gate above already classified `deep`
                # itself, so the named identity pins for staleness
                # without re-entering the named-pointee kind check
                # (which would misread a `*S` element as a struct
                # read).
                if deep.type_id:
                    self._pin_fact_identities(deep)
                pointee_id = deep.type_id or (
                    f"{bound_ref.binding_id}"
                    + "/pointee" * (extra + 1)
                )
                named_pointee = False
            else:
                pointee_id = binding.type.type_id
                if not pointee_id:
                    # A `p := &x` alias produces an unnamed `*int64`
                    # binding — classify the pointee by the pointer
                    # fact's `elem` (scalar-or-pointer admits,
                    # matching the named path; composite/absent
                    # pointees stay closed). The synthetic per-binding
                    # identity below can never be pinned nor
                    # redeclared, which is what the write side does
                    # too.
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
            if pointee_id:
                # `*p` returns the pointee VALUE, whose fact is the
                # dereferenced pointer's own `elem`: `type PS
                # *[]int64` under `p *PS` yields a PS pointer
                # (`elem` is PS's {pointer} fact — admit), while
                # `type PF *func` under `p PF` yields a func
                # (`elem` = {function} — close). Reading the
                # resolved named type's `elem` instead would
                # mis-classify a named-pointer pointee as ITS
                # pointee (`*p` on `p *PS` is not a slice).
                source = (
                    member.type
                    if member is not None
                    else binding.type
                )
                read_fact = (
                    source.elem
                    if source is not None and source.elem is not None
                    else (
                        target.type if target is not None else None
                    )
                )
                if read_fact is None or read_fact.kind not in {
                    "integer",
                    "boolean",
                    "pointer",
                }:
                    raise _Unsupported(
                        "non_parameter_reference", _span(node)
                    )
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
            or fn.generic
            or fn.variadic
            # A method's receiver is a leading signature slot like any
            # parameter: its declared fact must sit inside the admitted
            # kinds — a concrete named type's fact is `struct`/`pointer`
            # (scalar-named receivers arrive as `integer`/`boolean`).
            or (
                fn.receiver is not None
                and fn.receiver.type.kind
                not in {"integer", "boolean", "pointer", "struct"}
                and not (
                    fn.receiver.type.kind == "chan"
                    and fn.receiver.type.elem is not None
                    and fn.receiver.type.elem.kind in {"integer", "boolean"}
                )
            )
            # Pointer-typed parameters/results are admitted too: the
            # dep model tracks the *binding's* index, not the pointee,
            # and every use still passes the expression gates — so a
            # `*lib.T` param unlocks method calls on it while derefs,
            # field access and address-of stay closed. The pointee's
            # named/alias identity arrives on `type_id` and pins like
            # any other signature type.
            or any(
                p.type.kind
                not in {"integer", "boolean", "pointer", "struct",
                        "function"}
                and not (
                    # A `chan T` parameter admits under the
                    # external sync-resource model: the queue is
                    # shared with the caller, so sends, receives
                    # and closes record imported effects on the
                    # parameter's binding identity. Only a scalar
                    # element is modelled — a queued pointer would
                    # bind caller memory the model cannot scope.
                    p.type.kind == "chan"
                    and (
                        self._scalar_chan_fact(p.type)
                        # A `chan chan T` parameter admits too: ops on
                        # the outer queue record external effects,
                        # and a channel received from it binds as an
                        # external name — one level deep only.
                        or self._chan_chan_fact(p.type)
                    )
                    # A func-element collection parameter —
                    # `[]func` / `[N]func` / `map[K]func` — admits like
                    # the result form: the elements live in caller
                    # memory, so `fs[k]()` calls resolve opaque on the
                    # parameter's slot (deps of the parameter join the
                    # callee's read set). Exactly one level deep —
                    # `[][]func` stays closed.
                    or (
                        p.type.kind in {"slice", "array", "map"}
                        and p.type.elem is not None
                        and p.type.elem.kind == "function"
                    )
                )
                for p in fn.parameters
            )
            # A `struct` parameter/result (named or anonymous)
            # admits like a composite local: the binding carries
            # one conflated dep set for every field — `s.V = x`
            # folds into it, `s.V` reads it whole. The named
            # type's identity pins like any other signature type.
            or any(
                r.type.kind
                not in {"integer", "boolean", "pointer", "struct",
                        # A `func` result admits like a `func` parameter:
                        # the value carries no scalar deps — `return G`
                        # on a declared function reads dep-free — and the
                        # caller binds the name as an opaque func value
                        # whose calls resolve through the func-value path.
                        "function"}
                and not (
                    # A scalar-element `chan T` result admits under
                    # the same external sync-resource model a `chan`
                    # parameter uses: the callee hands the caller a
                    # shared queue, so ops on the bound result name
                    # record imported effects exactly like a
                    # parameter's do.
                    r.type.kind == "chan"
                    and (
                        self._scalar_chan_fact(r.type)
                        # A `chan chan T` result admits like the
                        # parameter form: the bound name joins the
                        # external model, so later `cc <- ch` /
                        # `<-cc` ops record external effects.
                        or self._chan_chan_fact(r.type)
                    )
                    # A func-element collection result —
                    # `[]func` / `[N]func` / `map[K]func` — admits
                    # like a scalar `func` result: elements carry
                    # no scalar deps, and the caller's `mk()[0]()`
                    # call runs opaque on the container's slot like
                    # an imported container member does.
                    or (
                        r.type.kind in {"slice", "array", "map"}
                        and r.type.elem is not None
                        and r.type.elem.kind == "function"
                    )
                )
                for r in fn.results
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
        # A method's receiver is the leading signature slot: it binds
        # like parameter index 0, so a `st.M(args)` call's actuals are
        # (receiver_deps, *arg_deps) and the callee summary's index 0
        # is the receiver.
        sig_params = (
            (fn.receiver, *fn.parameters)
            if fn.receiver is not None
            else fn.parameters
        )
        params = {p.binding_id: i for i, p in enumerate(sig_params) if p.binding_id}
        transfers: list[CallTransfer] = []
        count = [0]
        locals_: dict[str, frozenset[int]] = {}
        # A named result is an ordinary local pre-initialised to the zero
        # value — dep-free until a body statement writes to it. A
        # multi-result signature seeds every named slot the same way.
        for result in fn.results:
            if result.binding_id:
                locals_[result.binding_id] = frozenset()
        # A `struct` parameter's conflated dep set lives in `locals_`
        # like a composite local's (`s.V = x` folds in, `s.V` reads
        # it) — seed it with the parameter's own index so reads
        # carry the caller's provenance.
        for p in sig_params:
            if p.binding_id and p.type.kind == "struct":
                locals_[p.binding_id] = frozenset(
                    {params[p.binding_id]}
                )
        # Anonymous-struct signature slots declare their fields
        # inside the signature literal — anchor each binding's field
        # window there (a multi-name `s, t struct{...}` shares the
        # one literal after the last name).
        self._record_sig_struct_anchors(block.parent, body_key[0])
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
        saved_read_stack = self._read_stack
        saved_stmt_reads = self._stmt_reads
        saved_ptr_deps = self._ptr_deps
        saved_chan_aliases = self.chan_aliases
        saved_field_queues = self.field_chan_queues
        saved_external_chans = self.external_chan_locals
        saved_defer_result_deps = self._defer_result_deps
        saved_func_args = self._func_arg_invocations
        saved_call_arg_deps = self._call_arg_deps
        self.frames = []
        self.pinned = set()
        self.escaped = set()
        self.indirect_writes = frozenset()
        self._read_stack = []
        self._stmt_reads = {}
        self._ptr_deps = {}
        self.chan_aliases = {}
        self.field_chan_queues = {}
        self.external_chan_locals = set()
        self._defer_result_deps = frozenset()
        self._func_arg_invocations = {}
        self._call_arg_deps = {}
        # The summary embeds the function's declared parameter and
        # result type facts, so the named/alias identities they carry
        # pin it directly: redeclaring one makes this summary's
        # recorded facts stale even when its binding identity is
        # unchanged. Callers pin the same identities again at each
        # admitted call site.
        for p in (*sig_params, *fn.results):
            # Walk the whole fact tree — a `chan MyInt` parameter
            # carries its element's identity on `elem`, not the top
            # fact, so redeclaring the element type still flags
            # this summary stale.
            self._pin_fact_identities(p.type)
            # A func-typed slot (`f func(N) int64`) declares its inner
            # named types on the binding record — the func fact tree
            # holds none.
            pb = self.bindings.get(p.binding_id)
            if pb is not None:
                self.pinned.update(pb.signature_type_ids)
        try:
            self._sequence(
                statements, fn, params, locals_, transfers, count, deps,
                saw_return, False,
            )
        finally:
            pinned = tuple(sorted(self.pinned))
            reads = tuple(
                StatementRead(entry[0], entry[1])
                for entry in sorted(
                    self._stmt_reads.values(), key=lambda e: _key3(e[0])
                )
            )
            self.frames = saved_frames
            self.pinned = saved_pinned
            self.escaped = saved_escaped
            self.indirect_writes = saved_indirect
            self._read_stack = saved_read_stack
            self._stmt_reads = saved_stmt_reads
            self._ptr_deps = saved_ptr_deps
            self.chan_aliases = saved_chan_aliases
            self.field_chan_queues = saved_field_queues
            self.external_chan_locals = saved_external_chans
            self._defer_result_deps = saved_defer_result_deps
            self._func_arg_invocations = saved_func_args
            self._call_arg_deps = saved_call_arg_deps
            self.current_file = previous_file
        if not saw_return[0] and fn.results:
            # A void callee may fall off the end of its body — Go
            # treats that as an implicit bare `return`, which the
            # dep model already carries as nothing.
            raise _Unsupported("unsupported_body", fn.body)
        return self.result(
            fn,
            deps[0],
            tuple(sorted(transfers, key=lambda c: _key3(c.span))),
            pinned=pinned,
            statement_reads=reads,
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

    def _branch_sequence(self, children, *args: Any) -> None:
        """`_sequence` over a maybe-unexecuted scope copy — the body's
        writes only join back by union, so a closure literal bound
        inside keeps the skipped path's capture record too."""
        self._may_skip += 1
        try:
            self._sequence(children, *args)
        finally:
            self._may_skip -= 1

    def _branch_statement(self, node: Any, *args: Any) -> None:
        """The same marker for a single statement on a scope copy
        (a switch alternative, a for-update)."""
        self._may_skip += 1
        try:
            self.statement(node, *args)
        finally:
            self._may_skip -= 1

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
        # Passive read attribution: every dep set `expression` returns
        # while this statement walks lands on this frame (and on every
        # enclosing frame) — a nested statement's reads belong to the
        # outer statement too, like dep flow itself. A statement closed
        # by `_Unsupported` records nothing; the function gaps anyway.
        self._read_stack.append([])
        try:
            self._statement(
                node, fn, params, locals_, transfers, count, deps,
                saw_return, conditional,
            )
        finally:
            frame = self._read_stack.pop()
        # Same addressing `CallTransfer.span` uses — the file index is
        # part of the identity in a multi-file package.
        span = FileSpan(
            self.current_file, node.start_byte, node.end_byte
        )
        union = (
            frozenset().union(*frame) if frame else frozenset()
        )
        key = _key3(span)
        entry = self._stmt_reads.get(key)
        if entry is None:
            self._stmt_reads[key] = [span, union]
        else:
            # Loop fixed-point re-passes walk the same span again —
            # union, never replace, so the record stays idempotent.
            entry[1] |= union

    def _statement(
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
        self._conditional = conditional
        kind = node.type
        if kind in {"block", "statement_list"}:
            self._sequence(
                _children(node), fn, params, locals_, transfers, count,
                deps, saw_return, conditional,
            )
            return
        if kind == "return_statement":
            if (
                self._defer_result_deps
                and any(r.binding_id for r in fn.results)
            ):
                # Named results stay mutable after the result
                # expressions evaluate — a deferred may-write call
                # can still change them, bounded by its arguments.
                deps[0] |= self._defer_result_deps
            expressions = _children(node)
            if len(expressions) == 1 and expressions[0].type == "expression_list":
                expressions = _children(expressions[0])
            if len(expressions) == 0:
                if not fn.results:
                    # A bare `return` in a void callee carries
                    # nothing — the same implicit return a
                    # fall-off-the-end body gets.
                    saw_return[0] = True
                    return
                # A bare `return` is only legal with a named result — it
                # yields the result binding's current dependencies. With
                # several named results the conflated dep set unions
                # every slot: the caller cannot tell which result
                # position fed a bound name, matching the imported
                # multi-result model.
                result_ids = [
                    r.binding_id for r in fn.results if r.binding_id
                ]
                if len(result_ids) != len(fn.results) or not result_ids:
                    raise _Unsupported("unsupported_return", _span(node))
                result_deps = frozenset()
                for result_id in result_ids:
                    # A `r = q` store on a `chan` named result goes
                    # through `chan_aliases` (no dep set lands in
                    # `locals_[r]`) — resolve the queue root like an
                    # identifier read does so `return` carries q's deps.
                    result_root = self._chan_root(result_id)
                    if result_root in params:
                        result_deps |= frozenset(
                            {params[result_root]}
                        ) | self.indirect_writes
                    elif result_root in self.external_chan_locals:
                        result_deps |= (
                            locals_.get(result_root, frozenset())
                            | self.indirect_writes
                        )
                    else:
                        result_deps |= locals_.get(
                            result_root, frozenset()
                        )
                deps[0] |= result_deps
                self._record_read(result_deps)
            elif len(expressions) == 1:
                deps[0] |= self._return_expr_deps(
                    expressions[0], fn, params, locals_, transfers, count
                )
            elif len(expressions) == len(fn.results):
                # `return a, b` — every expression's deps fold into the
                # one conflated set, so a bound name may carry the
                # sibling slots' provenance too (the same
                # over-approximation the imported multi-result unpack
                # uses).
                for e in expressions:
                    deps[0] |= self._return_expr_deps(
                        e, fn, params, locals_, transfers, count
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
                    and not self._is_chan_recv(rights[0], len(lefts))
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
            # Tuple binds evaluate the pre-state in parallel — `a, h2
            # := g, h` or `h, g := g, h` — so the propagation below
            # reads the maps as they were BEFORE any store landed.
            captures_before = dict(self.closure_captures)
            pointee_before = set(self.pointee_closures)
            aliases_before = dict(self.func_aliases)
            opaque_before = set(self.opaque_callees)
            mv_before = dict(self.bound_method_values)
            mv_deps_before = dict(self.bound_method_receiver_deps)
            writes_before = dict(self.closure_writes)
            star_before = set(self.closure_star_writes)
            calls_before = set(self.closure_inner_calls)
            # Identifier-RHS pointer provenance reads the pre-state
            # too — `p, r := q, p` hands r the OLD p's pointer.
            rhs_ptrs: list = []
            for i in range(len(lefts)):
                src_ref = (
                    self.references.get(self.node_key(rights[i]))
                    if len(lefts) == len(rights)
                    and rights[i].type == "identifier"
                    else None
                )
                rhs_ptrs.append(
                    self._pointer_deps(
                        src_ref.binding_id, params, locals_
                    )
                    if src_ref is not None
                    else None
                )
            # Channel alias/passthrough binds resolve the pre-state
            # too — `a, c := g(a, b)` where `g` returns `q, p` hands
            # `c` the queue `a` named BEFORE slot 0 reseated `a` to
            # `b`'s (and an equal-width `a, b := b, a` swaps the
            # queues the same way).
            pre_chan_targets: list = [
                (
                    self._chan_alias_target(
                        (
                            rights[i]
                            if len(lefts) == len(rights)
                            else rights[0]
                        ),
                        locals_,
                        params,
                    )
                    or self._chan_result_passthrough(
                        (
                            rights[i]
                            if len(lefts) == len(rights)
                            else rights[0]
                        ),
                        locals_,
                        params,
                        i if len(rights) == 1 else 0,
                    )
                )
                for i in range(len(lefts))
            ]
            for i, (lhs, value) in enumerate(zip(lefts, values)):
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
                        # `h := func()...` — a bound closure carries its
                        # captured free-variable deps like a value.
                        "function",
                        # `ch := make(chan T)` — a local channel
                        # carries one conflated set of every sent
                        # value's deps; `<-ch` returns the union.
                        "chan",
                    }
                    # `st := P{...}` — a named composite local carries
                    # one conflated dep set for every field, and
                    # `fs := mk()` a `[]func`/`[N]func` container
                    # whose `fs[k]()` calls opaque on it.
                    and not self._is_local_composite(binding)
                    and not self._func_elem_collection(binding.type)
                    and not self._func_elem_nested_collection(
                        binding.type
                    )
                ):
                    raise _Unsupported("binding_unavailable", _span(node))
                if binding.type.kind == "chan" and not (
                    (
                        self._scalar_chan_binding(binding.id)
                        and (
                            (
                                len(lefts) == len(rights)
                                and (
                                    self._is_make_chan_call(rights[i])
                                    or self._chan_alias_target(
                                        rights[i], locals_, params
                                    )
                                    is not None
                                    or self._chan_result_call(rights[i])
                                    is not None
                                    # `c := <-cc` — a channel received
                                    # out of an external `chan chan`
                                    # queue binds an external name.
                                    or self._chan_chan_receive(
                                        rights[i], params
                                    )
                                )
                            )
                            # A multi-valued call's slot has no per-result
                            # RHS node — `ch, n := g()` admits when the
                            # callee declares a scalar `chan` in slot i;
                            # the name binds an external queue like
                            # `ch := g()` does.
                            or (
                                len(rights) == 1
                                and self._chan_result_call_at(rights[0], i)
                                is not None
                            )
                            # `c, ok := <-cc` — the value slot of a
                            # comma-ok receive out of an external
                            # `chan chan` queue binds an external
                            # name like `c := <-cc` does.
                            or (
                                len(rights) == 1
                                and self._is_chan_recv(
                                    rights[0], len(lefts)
                                )
                                and self._chan_chan_receive(
                                    rights[0], params
                                )
                            )
                        )
                    )
                    # `cc := G()` / `cc, n := G()` binding a
                    # callee-declared `chan chan T` result — the name
                    # joins the external model: later `cc <- ch` /
                    # `<-cc` ops record imported effects on it.
                    or (
                        self._chan_chan_fact(binding.type)
                        and (
                            (
                                len(lefts) == len(rights)
                                and self._chan_result_call(
                                    rights[i], self._chan_chan_fact
                                )
                                is not None
                            )
                            or (
                                len(rights) == 1
                                and self._chan_result_call_at(
                                    rights[0], i, self._chan_chan_fact
                                )
                                is not None
                            )
                        )
                    )
                ):
                    # `ch2 := ch` aliases one queue under a second
                    # name — sends through ch2 land in ch's dep set
                    # through `chan_aliases` — and `ch := g()` binds
                    # a callee-produced queue under the external
                    # model — but any other RHS (a receive, a
                    # non-chan call result) produces a queue the
                    # conflated dep set cannot model. Only `make`
                    # creates a channel in-fragment, an identifier
                    # copies one, a declared-`chan` call hands one
                    # over, and only a scalar element keeps queue
                    # contents inside the dep model.
                    raise _Unsupported("binding_unavailable", _span(node))
                chan_rhs = (
                    rights[i]
                    if len(lefts) == len(rights)
                    # A multi-valued call's chan slot shares the single
                    # RHS node — make/alias/passthrough all resolve to
                    # None on it, so the name takes the external model.
                    else rights[0]
                )
                if binding.type.kind == "chan" and not self._is_make_chan_call(
                    chan_rhs
                ):
                    # `c := g(q)` with `g`'s body `return ch` —
                    # c names q's queue, not a fresh external one.
                    # Both the alias and the passthrough resolved
                    # against the pre-state above.
                    pre_target = pre_chan_targets[i]
                    if pre_target is not None:
                        self.chan_aliases[binding.id] = pre_target.id
                    else:
                        # `c, ok := <-cc` reusing an existing `c` —
                        # `:=` may rebind a name in the same scope
                        # instead of shadowing it, so a stale
                        # `c := ch` alias must not keep `<-c`
                        # resolving to the old queue.
                        self.chan_aliases.pop(binding.id, None)
                        self.external_chan_locals.add(binding.id)
                        # `ch := lib.G(q)` — the imported callee
                        # may hand `q`'s queue back, so every
                        # `chan` argument joins the external
                        # model and its current contents seed
                        # the bound name's slot.
                        for arg_root in (
                            self._imported_chan_result_args(
                                chan_rhs,
                                locals_,
                                params,
                                i if len(rights) == 1 else 0,
                            )
                        ):
                            self.external_chan_locals.add(arg_root)
                            value = value | locals_.get(
                                arg_root,
                                (
                                    frozenset({params[arg_root]})
                                    if arg_root in params
                                    else frozenset()
                                ),
                            )
                if binding.type.kind == "function" or (
                    self._func_elem_collection(binding.type)
                    or self._func_elem_nested_collection(binding.type)
                ):
                    # `f := mk(ch)` — the returned closure may
                    # capture the queue it received, so the call's
                    # `chan` arguments join the external model: a
                    # later `ch <- x` broadcasts into
                    # `indirect_writes`, which the opaque `f()`
                    # call then observes. A func-element container
                    # binds the same way — `fs := mk(ch)` elements
                    # may receive on `ch`.
                    value = value | self._func_result_chan_args(
                        chan_rhs, locals_, params
                    )
                if not conditional:
                    self._ptr_deps[binding.id] = (
                        rhs_ptrs[i]
                        if rhs_ptrs[i] is not None
                        else value
                    )
                else:
                    self._ptr_deps[binding.id] = (
                        self._pointer_deps(
                            binding.id, params, locals_
                        )
                        | (
                            rhs_ptrs[i]
                            if rhs_ptrs[i] is not None
                            else value
                        )
                    )
                self._store(locals_, params, binding.id, value, conditional)
                # `h2 := h` — a copied closure keeps its captured
                # bindings: propagate the capture record so `h2()`
                # resolves them at call time like `h()` does. A
                # non-closure RHS clears a capture set an earlier
                # literal left on a reused name.
                if (
                    len(lefts) == len(rights)
                    and rights[i].type == "identifier"
                ):
                    src_ref = self.references.get(
                        self.node_key(rights[i])
                    )
                    src_id = (
                        src_ref.binding_id if src_ref is not None else None
                    )
                    if (
                        src_id is not None
                        and src_id in captures_before
                    ):
                        self.closure_captures[binding.id] = (
                            captures_before[src_id]
                        )
                    else:
                        self.closure_captures.pop(binding.id, None)
                    if (
                        src_id is not None
                        and src_id in pointee_before
                    ):
                        self.pointee_closures.add(binding.id)
                    else:
                        self.pointee_closures.discard(binding.id)
                    # `g := f` where f is a bound method value copies
                    # the (method, receiver) pair like the captures —
                    # the frozen receiver deps copy with it, read
                    # from the pre-state so `f, g := g, f` swaps.
                    src_mv = (
                        mv_before.get(src_id)
                        if src_id is not None
                        else None
                    )
                    if src_mv is not None:
                        self.bound_method_values[binding.id] = src_mv
                        if src_id in mv_deps_before:
                            self.bound_method_receiver_deps[
                                binding.id
                            ] = mv_deps_before[src_id]
                        else:
                            self.bound_method_receiver_deps.pop(
                                binding.id, None
                            )
                    else:
                        self._drop_bound_method(binding.id)
                    if src_id is not None and src_id in writes_before:
                        self.closure_writes[binding.id] = (
                            writes_before[src_id]
                        )
                    else:
                        self.closure_writes.pop(binding.id, None)
                    if src_id is not None and src_id in star_before:
                        self.closure_star_writes.add(binding.id)
                    else:
                        self.closure_star_writes.discard(binding.id)
                    if src_id is not None and src_id in calls_before:
                        self.closure_inner_calls.add(binding.id)
                    else:
                        self.closure_inner_calls.discard(binding.id)
                    # `h2 := h` inherits h's opaque mark too — the
                    # copy resolves the same mixed alternatives.
                    if (
                        src_id is not None
                        and src_id in opaque_before
                    ):
                        self.opaque_callees.add(binding.id)
                    else:
                        self.opaque_callees.discard(binding.id)
                    # `h := G` binds a declared function name; `h2 :=
                    # h` inherits the alias h recorded.
                    self._propagate_func_alias(
                        binding.id, src_id, aliases_before, params,
                        conditional,
                    )
                    src_bound = (
                        self.bindings.get(src_id)
                        if src_id is not None
                        else None
                    )
                    if (
                        src_bound is not None
                        and (
                            self._func_elem_collection(
                                src_bound.type
                            )
                            or self._func_elem_nested_collection(
                                src_bound.type
                            )
                        )
                        and (
                            self._func_elem_collection(
                                binding.type
                            )
                            or self._func_elem_nested_collection(
                                binding.type
                            )
                        )
                    ):
                        # `fs2 := fs` — the copy shares the
                        # backing: element stores through either
                        # name reach both.
                        self._func_elem_share(binding.id, src_id)
                elif (
                    len(lefts) == len(rights)
                    and rights[i].type == "selector_expression"
                ):
                    # `f := s.M` — bind the method value's (method,
                    # receiver) pair under the fresh name; a
                    # non-method selector RHS clears it.
                    self._record_bound_method(
                        binding.id,
                        self._method_value_parts(rights[i]),
                        params, locals_,
                    )
                    # A method value carries no literal captures —
                    # an earlier literal's records drop too, or `f()`
                    # would resolve the stale closure's reads.
                    self.closure_captures.pop(binding.id, None)
                    self.pointee_closures.discard(binding.id)
                    self.closure_writes.pop(binding.id, None)
                    self.closure_star_writes.discard(binding.id)
                    self.closure_inner_calls.discard(binding.id)
                    # A selector RHS stores a value the alias model
                    # cannot resolve — any earlier alias drops.
                    self.func_aliases.pop(binding.id, None)
                    self.opaque_callees.discard(binding.id)
                elif len(lefts) == len(rights):
                    if rights[i].type == "func_literal":
                        # `f := func()...` — the literal just wrote
                        # the name's records; only an earlier alias
                        # cannot resolve through it. The fresh
                        # declaration binds EXACTLY this literal, so
                        # an opaque mark a previous loop iteration's
                        # conditional copy left on the reused name
                        # must drop too — otherwise the call right
                        # after redeclaration folds a callback that
                        # cannot run.
                        self.func_aliases.pop(binding.id, None)
                        self.opaque_callees.discard(binding.id)
                    elif self._is_func_elem_composite(
                        rights[i], binding.id
                    ):
                        # `fs := []func(){…}` — the element
                        # literals recorded captures under this
                        # container during RHS eval; keep them,
                        # and adopt the func-value records an
                        # element identifier carries (`{cl}`).
                        self._adopt_container_element_records(
                            rights[i], binding.id
                        )
                    elif (
                        append_cont := self._func_elem_append_target(
                            rights[i], locals_
                        )
                    ) is not None and self._func_elem_collection(
                        binding.type
                    ):
                        # `fs2 := append(fs, f)` — the result may
                        # reuse the argument's array: the fresh
                        # name shares that backing and sees the
                        # container's elements (including the one
                        # this append added).
                        self._func_elem_share(
                            binding.id, append_cont
                        )
                        self._adopt_element_records(
                            append_cont, binding.id
                        )
                    else:
                        # Any other RHS clears every func-value record
                        # an earlier bind left on the reused name — a
                        # call through it resolves the new value, not
                        # a stale capture set or method pair.
                        self._drop_func_value_records(binding.id)
                else:
                    # A multi-valued RHS resolves to no single
                    # function either — every record drops like a
                    # non-identifier rebind.
                    self._drop_func_value_records(binding.id)
                # `cp := st` — a copied anonymous struct shares st's
                # declared type, so cp's fields follow st's anchor,
                # not cp's own name. `p := G(x)` declares its fields
                # inside G's result signature — the literal anchors
                # the window the same way.
                if (
                    binding.type.kind == "struct"
                    and not binding.type.type_id
                ):
                    lit_result = (
                        self._call_result_struct_literal(rights[0], i)
                        if len(lefts) != len(rights)
                        else self._call_result_struct_literal(
                            rights[i]
                        )
                    )
                    anchor = (
                        FileSpan(
                            lit_result[1],
                            lit_result[0].start_byte,
                            lit_result[0].start_byte,
                        )
                        if lit_result is not None
                        else None
                    )
                    src_id = None
                    if (
                        len(lefts) == len(rights)
                        and rights[i].type == "identifier"
                    ):
                        src_ref = self.references.get(
                            self.node_key(rights[i])
                        )
                        src_id = (
                            src_ref.binding_id
                            if src_ref is not None
                            else None
                        )
                    if anchor is not None:
                        self.anon_struct_anchor[binding.id] = anchor
                        self.anon_struct_field_names[binding.id] = (
                            self._struct_literal_field_names(
                                lit_result[0]
                            )
                        )
                    elif src_id is not None:
                        src_binding = self.bindings.get(src_id)
                        anchor = self.anon_struct_anchor.get(
                            src_id
                        ) or getattr(src_binding, "span", None)
                        if anchor is not None:
                            self.anon_struct_anchor[binding.id] = anchor
                            src_names = (
                                self.anon_struct_field_names.get(src_id)
                            )
                            if src_names is not None:
                                self.anon_struct_field_names[
                                    binding.id
                                ] = src_names
                            else:
                                self.anon_struct_field_names.pop(
                                    binding.id, None
                                )
                        else:
                            self.anon_struct_anchor.pop(
                                binding.id, None
                            )
                            self.anon_struct_field_names.pop(
                                binding.id, None
                            )
                    else:
                        self.anon_struct_anchor.pop(binding.id, None)
                        self.anon_struct_field_names.pop(
                            binding.id, None
                        )
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
                        or self._is_chan_recv(
                            value_nodes[0], len(names)
                        )
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
                # See the short-declaration store loop: tuple values
                # evaluate against the pre-state, so copies read the
                # capture maps as they were before any store.
                captures_before = dict(self.closure_captures)
                pointee_before = set(self.pointee_closures)
                aliases_before = dict(self.func_aliases)
                opaque_before = set(self.opaque_callees)
                mv_before = dict(self.bound_method_values)
                mv_deps_before = dict(self.bound_method_receiver_deps)
                writes_before = dict(self.closure_writes)
                star_before = set(self.closure_star_writes)
                calls_before = set(self.closure_inner_calls)
                rhs_ptrs = []
                for i in range(len(names)):
                    src_ref = (
                        self.references.get(
                            self.node_key(value_nodes[i])
                        )
                        if len(names) == len(value_nodes)
                        and value_nodes[i].type == "identifier"
                        else None
                    )
                    rhs_ptrs.append(
                        self._pointer_deps(
                            src_ref.binding_id, params, locals_
                        )
                        if src_ref is not None
                        else None
                    )
                for i, (name, value) in enumerate(zip(names, values)):
                    if name.text == b"_":
                        continue
                    binding = self.bindings_by_span.get(self.node_key(name))
                    if binding is None or (
                        binding.type.kind
                        not in {
                            "integer",
                            "boolean",
                            "pointer",
                            # `var h func() T` / `var h = func()...` —
                            # a bound closure like the short-decl form.
                            "function",
                            # `var ch chan T` — a local channel like
                            # the make(chan) form.
                            "chan",
                        }
                        # `var fs = mk()` / `var fs []func() T` — a
                        # `[]func`/`[N]func` container like the
                        # short-decl form.
                        and not self._is_local_composite(binding)
                        and not self._func_elem_collection(binding.type)
                        and not self._func_elem_nested_collection(
                            binding.type
                        )
                    ):
                        raise _Unsupported(
                            "binding_unavailable", _span(spec)
                        )
                    chan_chan_declared = self._chan_chan_fact(
                        binding.type
                    ) and bool(value_nodes) and (
                        (
                            len(value_nodes) == len(names)
                            and self._chan_result_call(
                                value_nodes[i], self._chan_chan_fact
                            )
                            is not None
                        )
                        or (
                            len(value_nodes) == 1
                            and len(names) > 1
                            and self._chan_result_call_at(
                                value_nodes[0], i, self._chan_chan_fact
                            )
                            is not None
                        )
                    )
                    if (
                        binding.type.kind == "chan"
                        and (
                            (
                                not self._scalar_chan_binding(binding.id)
                                # `var cc = G()` — a `chan chan T`
                                # binding admits only a callee-declared
                                # `chan chan` result, like `cc := G()`.
                                and not chan_chan_declared
                            )
                            # `var ch, n = G(q)` — a multi-valued
                            # call admits per slot like the
                            # short-decl form when the callee's
                            # declared signature puts a scalar chan
                            # at this name's position.
                            or (
                                value_nodes
                                and len(names) != len(value_nodes)
                                and not (
                                    len(value_nodes) == 1
                                    and self._chan_result_call_at(
                                        value_nodes[0], i
                                    )
                                    is not None
                                )
                                and not (
                                    len(value_nodes) == 1
                                    and self._is_chan_recv(
                                        value_nodes[0], len(names)
                                    )
                                    and self._chan_chan_receive(
                                        value_nodes[0], params
                                    )
                                )
                                and not chan_chan_declared
                            )
                            or (
                                value_nodes
                                and len(value_nodes) == len(names)
                                and not self._is_make_chan_call(
                                    value_nodes[i]
                                )
                                and self._chan_alias_target(
                                    value_nodes[i], locals_, params
                                )
                                is None
                                and self._chan_result_call(
                                    value_nodes[i]
                                )
                                is None
                                and not chan_chan_declared
                            )
                        )
                    ):
                        # `var ch2 = ch` aliases one queue under a
                        # second name like `ch2 := ch`; a non-scalar
                        # element (`var q chan chan T`) transports
                        # channel values the dep model cannot hold,
                        # and any RHS that is neither `make` nor a
                        # channel identifier produces an unmodelled
                        # queue — all stay closed.
                        raise _Unsupported(
                            "binding_unavailable", _span(spec)
                        )
                    if (
                        binding.type.kind == "chan"
                        and value_nodes
                        and len(value_nodes) == 1
                        and len(names) > 1
                    ):
                        # `var ch, n = G(q)` — the chan-typed slot
                        # binds the callee's passthrough queue when
                        # it returns an argument unchanged, else a
                        # fresh external one (the probe cannot see a
                        # queue handed back through a callee-local
                        # alias, so external keeps sends broadcast).
                        target = self._chan_result_passthrough(
                            value_nodes[0], locals_, params, i
                        )
                        if target is not None:
                            self.chan_aliases[binding.id] = target.id
                        else:
                            self.external_chan_locals.add(binding.id)
                            for arg_root in (
                                self._imported_chan_result_args(
                                    value_nodes[0],
                                    locals_,
                                    params,
                                    i,
                                )
                            ):
                                self.external_chan_locals.add(
                                    arg_root
                                )
                                value = value | locals_.get(
                                    arg_root,
                                    (
                                        frozenset({params[arg_root]})
                                        if arg_root in params
                                        else frozenset()
                                    ),
                                )
                    elif (
                        binding.type.kind == "chan"
                        and value_nodes
                        and not self._is_make_chan_call(value_nodes[i])
                    ):
                        chan_alias = self._chan_alias_target(
                            value_nodes[i], locals_, params
                        )
                        if chan_alias is not None:
                            self.chan_aliases[binding.id] = chan_alias.id
                        elif self._chan_chan_fact(binding.type):
                            # `var cc = G()` — a callee-declared
                            # `chan chan` result binds an external
                            # queue like `cc := G()` does.
                            self.external_chan_locals.add(binding.id)
                        elif self._chan_result_call(value_nodes[i]) is not None:
                            passthrough = self._chan_result_passthrough(
                                value_nodes[i], locals_, params
                            )
                            if passthrough is not None:
                                self.chan_aliases[binding.id] = (
                                    passthrough.id
                                )
                            else:
                                self.external_chan_locals.add(
                                    binding.id
                                )
                                for arg_root in (
                                    self._imported_chan_result_args(
                                        value_nodes[i], locals_, params
                                    )
                                ):
                                    self.external_chan_locals.add(
                                        arg_root
                                    )
                                    value = value | locals_.get(
                                        arg_root,
                                        (
                                            frozenset(
                                                {params[arg_root]}
                                            )
                                            if arg_root in params
                                            else frozenset()
                                        ),
                                    )
                    if (
                        binding.type.kind == "function"
                        or self._func_elem_collection(binding.type)
                        or self._func_elem_nested_collection(
                            binding.type
                        )
                    ) and value_nodes:
                        # `var f = mk(ch)` — like the short-decl
                        # form, a returned closure may capture the
                        # call's `chan` arguments.
                        value = value | self._func_result_chan_args(
                            (
                                value_nodes[i]
                                if len(names) == len(value_nodes)
                                else value_nodes[0]
                            ),
                            locals_,
                            params,
                        )
                    if not conditional:
                        self._ptr_deps[binding.id] = (
                            rhs_ptrs[i]
                            if rhs_ptrs[i] is not None
                            else value
                        )
                    else:
                        self._ptr_deps[binding.id] = (
                            self._pointer_deps(
                                binding.id, params, locals_
                            )
                            | (
                                rhs_ptrs[i]
                                if rhs_ptrs[i] is not None
                                else value
                            )
                        )
                    self._store(
                        locals_, params, binding.id, value, conditional
                    )
                    # `var h2 = h` — a copied closure keeps its
                    # captured bindings, like `h2 := h`.
                    if (
                        not multi
                        and value_nodes
                        and len(names) == len(value_nodes)
                        and value_nodes[i].type == "identifier"
                    ):
                        src_ref = self.references.get(
                            self.node_key(value_nodes[i])
                        )
                        src_id = (
                            src_ref.binding_id
                            if src_ref is not None
                            else None
                        )
                        if (
                            src_id is not None
                            and src_id in captures_before
                        ):
                            self.closure_captures[binding.id] = (
                                captures_before[src_id]
                            )
                        else:
                            self.closure_captures.pop(binding.id, None)
                        src_mv = (
                            mv_before.get(src_id)
                            if src_id is not None
                            else None
                        )
                        if src_mv is not None:
                            self.bound_method_values[binding.id] = (
                                src_mv
                            )
                            if src_id in mv_deps_before:
                                self.bound_method_receiver_deps[
                                    binding.id
                                ] = mv_deps_before[src_id]
                            else:
                                self.bound_method_receiver_deps.pop(
                                    binding.id, None
                                )
                        else:
                            self._drop_bound_method(binding.id)
                        if (
                            src_id is not None
                            and src_id in pointee_before
                        ):
                            self.pointee_closures.add(binding.id)
                        else:
                            self.pointee_closures.discard(binding.id)
                        if (
                            src_id is not None
                            and src_id in writes_before
                        ):
                            self.closure_writes[binding.id] = (
                                writes_before[src_id]
                            )
                        else:
                            self.closure_writes.pop(binding.id, None)
                        if (
                            src_id is not None
                            and src_id in star_before
                        ):
                            self.closure_star_writes.add(binding.id)
                        else:
                            self.closure_star_writes.discard(
                                binding.id
                            )
                        if (
                            src_id is not None
                            and src_id in calls_before
                        ):
                            self.closure_inner_calls.add(binding.id)
                        else:
                            self.closure_inner_calls.discard(
                                binding.id
                            )
                        if (
                            src_id is not None
                            and src_id in opaque_before
                        ):
                            self.opaque_callees.add(binding.id)
                        else:
                            self.opaque_callees.discard(binding.id)
                        self._propagate_func_alias(
                            binding.id, src_id, aliases_before,
                            params, conditional,
                        )
                        src_bound = (
                            self.bindings.get(src_id)
                            if src_id is not None
                            else None
                        )
                        if (
                            src_bound is not None
                            and (
                                self._func_elem_collection(
                                    src_bound.type
                                )
                                or self._func_elem_nested_collection(
                                    src_bound.type
                                )
                            )
                            and (
                                self._func_elem_collection(
                                    binding.type
                                )
                                or self._func_elem_nested_collection(
                                    binding.type
                                )
                            )
                        ):
                            # `var fs2 = fs` — shares the backing
                            # like `fs2 := fs`.
                            self._func_elem_share(
                                binding.id, src_id
                            )
                        # `var cp = st` — a copied anonymous struct
                        # shares st's anchor, like `cp := st`. An
                        # explicit `struct{...}` type on the spec
                        # declares cp's own fields right after its
                        # name instead, so the binding's default
                        # span anchor already covers them — copying
                        # st's would point the window at the wrong
                        # literal's fields.
                        if (
                            binding.type.kind == "struct"
                            and not binding.type.type_id
                            and src_id is not None
                            and spec.child_by_field_name("type") is None
                        ):
                            src_binding = self.bindings.get(src_id)
                            anchor = self.anon_struct_anchor.get(
                                src_id
                            ) or getattr(src_binding, "span", None)
                            if anchor is not None:
                                self.anon_struct_anchor[
                                    binding.id
                                ] = anchor
                                src_names = (
                                    self.anon_struct_field_names.get(
                                        src_id
                                    )
                                )
                                if src_names is not None:
                                    self.anon_struct_field_names[
                                        binding.id
                                    ] = src_names
                                else:
                                    self.anon_struct_field_names.pop(
                                        binding.id, None
                                    )
                            else:
                                self.anon_struct_anchor.pop(
                                    binding.id, None
                                )
                                self.anon_struct_field_names.pop(
                                    binding.id, None
                                )
                    elif (
                        not multi
                        and value_nodes
                        and len(names) == len(value_nodes)
                        and value_nodes[i].type
                        == "selector_expression"
                    ):
                        # `var f = s.M` — bind the method value's
                        # (method, receiver) pair like `f := s.M`.
                        self._record_bound_method(
                            binding.id,
                            self._method_value_parts(value_nodes[i]),
                            params, locals_,
                        )
                        # A method value carries no literal captures —
                        # earlier closure records drop like `f := s.M`.
                        self.closure_captures.pop(binding.id, None)
                        self.pointee_closures.discard(binding.id)
                        self.closure_writes.pop(binding.id, None)
                        self.closure_star_writes.discard(binding.id)
                        self.closure_inner_calls.discard(binding.id)
                        # Non-identifier RHS — any earlier alias drops.
                        self.func_aliases.pop(binding.id, None)
                    elif not multi and value_nodes:
                        if value_nodes[i].type == "func_literal":
                            # `var f = func()...` — the literal just
                            # wrote the name's records; only a method
                            # pair or alias cannot resolve through it.
                            self._drop_bound_method(binding.id)
                            self.func_aliases.pop(binding.id, None)
                        elif self._is_func_elem_composite(
                            value_nodes[i], binding.id
                        ):
                            # `var fs = []func(){…}` — keep the
                            # element literals' capture records
                            # and adopt identifier elements'.
                            self._adopt_container_element_records(
                                value_nodes[i], binding.id
                            )
                        elif (
                            (
                                append_cont
                                := self._func_elem_append_target(
                                    value_nodes[i], locals_
                                )
                            )
                            is not None
                            and self._func_elem_collection(
                                binding.type
                            )
                        ):
                            # `var fs2 = append(fs, f)` — shares
                            # the argument's backing and sees its
                            # elements like `fs2 := append(fs, f)`.
                            self._func_elem_share(
                                binding.id, append_cont
                            )
                            self._adopt_element_records(
                                append_cont, binding.id
                            )
                        else:
                            self._drop_func_value_records(binding.id)
                    else:
                        # `var h = (f)` / `var h = f()` / a
                        # multi-valued RHS — same non-identifier drop
                        # the `:=` path applies.
                        self._drop_func_value_records(binding.id)
                    # `var p = G(x)` — an anonymous-struct result's
                    # fields live inside G's signature literal, like
                    # `p := G(x)`; anchor the field window there.
                    if (
                        binding.type.kind == "struct"
                        and not binding.type.type_id
                        and spec.child_by_field_name("type") is None
                        and (i < len(value_nodes) or multi)
                    ):
                        lit_result = (
                            self._call_result_struct_literal(
                                value_nodes[0], i
                            )
                            if multi
                            else self._call_result_struct_literal(
                                value_nodes[i]
                            )
                        )
                        if lit_result is not None:
                            self.anon_struct_anchor[binding.id] = (
                                FileSpan(
                                    lit_result[1],
                                    lit_result[0].start_byte,
                                    lit_result[0].start_byte,
                                )
                            )
                            self.anon_struct_field_names[
                                binding.id
                            ] = self._struct_literal_field_names(
                                lit_result[0]
                            )
                    # `var a, b struct{...}` — the literal follows the
                    # LAST name, so every earlier name's fields anchor
                    # there, not at its own span (whose window closes
                    # at the next name, a scoped binding). Every
                    # explicit-spec var records the literal's direct
                    # names: a single-name `var s struct{...}` whose
                    # field resolves to an earlier identical literal's
                    # (unified types) needs the same admission check
                    # without needing an anchor — s's own span already
                    # precedes its literal.
                    if (
                        binding.type.kind == "struct"
                        and not binding.type.type_id
                        and spec.child_by_field_name("type") is not None
                    ):
                        literal = spec.child_by_field_name("type")
                        if literal.type == "struct_type":
                            self.anon_struct_field_names[
                                binding.id
                            ] = self._struct_literal_field_names(
                                literal
                            )
                        if len(names) > 1:
                            last = self.bindings_by_span.get(
                                self.node_key(names[-1])
                            )
                            last_span = getattr(last, "span", None)
                            if last_span is not None:
                                self.anon_struct_anchor[
                                    binding.id
                                ] = last_span
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
            ptr_scope = dict(self._ptr_deps)
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
            ptr_branch = dict(self._ptr_deps)
            self._branch_sequence(
                _children(consequence), fn, params, branch, transfers,
                count, deps, saw_return, conditional,
            )
            self._join(scope, branch, params)
            self._join_ptr(ptr_branch, params)
            alternative = node.child_by_field_name("alternative")
            if alternative is not None:
                branch = dict(scope)
                ptr_branch = dict(self._ptr_deps)
                if alternative.type == "if_statement":
                    self._branch_statement(
                        alternative, fn, params, branch, transfers,
                        count, deps, saw_return, conditional,
                    )
                else:
                    self._branch_sequence(
                        _children(alternative), fn, params, branch,
                        transfers, count, deps, saw_return, conditional,
                    )
                self._join(scope, branch, params)
                self._join_ptr(ptr_branch, params)
            if initializer is not None:
                self._join(locals_, scope, params)
                self._join_ptr(ptr_scope, params)
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
                    or self._is_chan_recv(rights[0], len(lefts))
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
            # LHS positions naming a `chan`-typed package var or
            # imported member — `GC = ch` reseats the external queue
            # operand to the RHS queue: no binding tracks package
            # state, so the stored queue's dependencies broadcast
            # into `indirect_writes` (like a send does) for a later
            # `<-GC`/`range GC` read to observe.
            chan_write_targets: set[int] = set()
            # `p.C = ch` reseats which queue the field names: index →
            # the leaf `chan` member, so the store can union the RHS
            # queue's tokens into the member's may-set.
            field_chan_lhs: dict[int, Any] = {}
            # `fs[i] = f` — an element store into a bound func-element
            # container keeps the stored value's records under the
            # container's name; the store loop unions rather than
            # copying like a plain rebind would.
            func_elem_targets: set[int] = set()
            # An element store's holder set resolves like the
            # destination operand itself — against the pre-state —
            # but a name an earlier parallel store re-shared
            # (`a2, a[0] = a, f`) joins the group only at store
            # landing time. Snapshot the resolution-time members;
            # the store unions them with the landing-time group so
            # both `a, a[0] = b, f` (old sharers keep the written
            # array) and the re-share case reach the right names.
            func_elem_holders: dict[int, frozenset[str]] = {}
            # Names an earlier parallel store detached from a shared
            # backing (`a2, a[0] = b, f` reseats `a2` before the
            # element write lands) no longer share that backing —
            # subtract them from the resolution-time snapshot.
            func_elem_reseated: set[str] = set()
            # Which backing each reseated name landed on, as the
            # resolution-time member set of its RHS source — `b`
            # in `a, b, c = d, a, append(a, z)` reseats onto the
            # backing `a` named at eval time (the same one `b`
            # already held), so it stays an append sharer even
            # though no surviving member name groups with it.
            func_elem_reseat_backings: dict[str, set[str]] = {}
            # A stored map key's deps broadcast into
            # `indirect_writes` only when the store lands — the RHS
            # of the same statement reads the pre-state, so the
            # union waits until after `values` evaluates below:
            # `(*p)[k], r = 1, (*p)[0]` reads `(*p)[0]` without
            # `k`'s deps.
            pending_map_key_deps = frozenset()
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
                            package_write = self._package_var_write(lhs)
                            if package_write is None:
                                raise _Unsupported(
                                    "binding_unavailable", _span(lhs)
                                )
                            binding, extras, _ = package_write
                            self._record_package_write(
                                lhs, binding, extras,
                                fn, params, locals_, transfers, count,
                            )
                            if self._scalar_chan_binding(binding.id):
                                chan_write_targets.add(len(refs))
                            refs.append(None)
                            continue
                        member, extras, _ = member_write
                        self._record_member_write(
                            lhs, member, extras,
                            fn, params, locals_, transfers, count,
                        )
                        if self._scalar_chan_fact(member.type):
                            chan_write_targets.add(len(refs))
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
                    type_id, ref, nested = write_target
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
                    # A bound-pointer base (a declared `type_id`) also
                    # broadcasts the store into `indirect_writes`: the
                    # field lives in external memory like `*q = v`, so
                    # a read through a DIFFERENT aliased pointer
                    # (`q.F = v; return p.F`) must observe it too. A
                    # local composite (empty `type_id`) keeps the
                    # precise accumulate-only fold. `nested` marks a
                    # store reached through a stored pointer field
                    # (`p.Next.V = v`) — computing the destination
                    # reads that field's contents too.
                    refs.append((ref, True, bool(type_id), nested))
                    field_chan = self._bound_field_chan(
                        lhs, locals_, params
                    )
                    if field_chan is not None:
                        field_chan_lhs[len(refs) - 1] = field_chan[1]
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
                    if (
                        not saw_deref
                        and self._scalar_chan_fact(member.type)
                    ):
                        chan_write_targets.add(len(refs) - 1)
                    continue
                # A package-level `var` — `G.V = v`, `G[i] = v`,
                # `*GP = v` — mutates package state the same way: the
                # var's binding identity records the mutation (in
                # `known`, so `stale_dependents` stays honest) and the
                # stored value's dependencies drop — unless the store
                # crosses the var's pointer, which may aim at any
                # escaped binding like `*lib.PV = v` does.
                package_write = self._package_var_write(lhs)
                if package_write is not None:
                    binding, extras, saw_deref = package_write
                    self._record_package_write(
                        lhs, binding, extras,
                        fn, params, locals_, transfers, count,
                    )
                    refs.append(_ALIAS_FOLD if saw_deref else None)
                    if (
                        not saw_deref
                        and self._scalar_chan_binding(binding.id)
                    ):
                        chan_write_targets.add(len(refs) - 1)
                    continue
                # `(*p)[i] = v` — a store through a bound pointer
                # whose pointee is a container writes element memory
                # no binding tracks: the pointee identity records
                # the external mutation (`effects` unknown) and the
                # index expressions evaluate in order. The fold is
                # required — a later `(*q)[j]` read must observe this
                # store through `indirect_writes`.
                bound_write = self._bound_container_write(
                    lhs, locals_, params
                )
                if bound_write is not None:
                    pointee_id, extras, fact, ref = bound_write
                    # The store's destination is computed from the
                    # pointer itself — read its provenance, not the
                    # folded element contents. `(*p)[i] += v` also
                    # reads the old element — `deps(p) ∪`
                    # `indirect_writes` like the read side.
                    dest_deps = self._pointer_deps(
                        ref.binding_id, params, locals_
                    )
                    if compound:
                        dest_deps = dest_deps | self.indirect_writes
                    self._record_read(dest_deps)
                    self._pin_fact_identities(fact)
                    map_key_deps = frozenset()
                    for extra in reversed(extras):
                        if extra.type in _INDEX_LITERALS:
                            continue
                        extra_deps = self.expression(
                            extra, fn, params, locals_,
                            transfers, count, 0,
                        )
                        self._record_read(extra_deps)
                        if fact.kind == "map" and extra is extras[0]:
                            # A map key is stored data — `(*p)[b]=1`
                            # stores `b`'s value, so a later key read
                            # (`for k := range *p`) must observe `b`'s
                            # deps through the broadcast. `extras` is
                            # innermost-first, so `extras[0]` is the
                            # index into the written map — in
                            # `(*p)[i][7] = 1` (a slice of maps) `i`
                            # only selects which map receives the
                            # store; `7` is the stored key.
                            map_key_deps |= extra_deps
                    pending_map_key_deps |= map_key_deps
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
                # `(*p)[i].F = v` — a field store through the
                # element a bound container pointee's index selects
                # writes external element memory no binding tracks:
                # the leaf field's own identity records the mutation
                # and the index expressions evaluate for their
                # effects. The alias fold is required — a later
                # `(*q)[j].F`/`(*p)[i].F` read observes the store
                # through `indirect_writes`.
                indexed_field = self._bound_pointee_index_field(
                    lhs, locals_, params
                )
                if indexed_field is not None:
                    (
                        _root, _pid, fact, extras, field_member,
                        mid_members, ref,
                    ) = indexed_field
                    self._pin_fact_identities(fact)
                    for mid_member in mid_members:
                        self._pin_fact_identities(mid_member.type)
                    if field_member.type is not None:
                        self._pin_fact_identities(field_member.type)
                    for extra in reversed(extras):
                        if extra.type in _INDEX_LITERALS:
                            continue
                        self._record_read(
                            self.expression(
                                extra, fn, params, locals_,
                                transfers, count, 0,
                            )
                        )
                    # Same pointer-read as `(*p)[i] = v` — the field
                    # store's destination resolves through the
                    # bound pointer; the indexes evaluate first so a
                    # call in one can add indirect stores the store's
                    # own read observes.
                    dest_deps = self._pointer_deps(
                        ref.binding_id, params, locals_
                    )
                    if compound:
                        dest_deps = dest_deps | self.indirect_writes
                    self._record_read(dest_deps)
                    transfers.append(
                        CallTransfer(
                            FileSpan(
                                self.current_file,
                                lhs.start_byte,
                                lhs.end_byte,
                            ),
                            field_member.id,
                            (),
                            frozenset(),
                            imported=True,
                        )
                    )
                    refs.append(_ALIAS_FOLD)
                    continue
                # `*p = v` — a store through a bound pointer lands in
                # memory the dep model does not track: the pointee's
                # declared identity records the external mutation
                # (`effects` reports `unknown`), and the stored
                # value's dependencies fold into every escaped
                # binding because `p := &x` may have aimed the
                # pointer at any of them — the same approximation
                # `*lib.PV = v` uses.
                bound_ptr = self._bound_pointer_write(
                    lhs, locals_, params
                )
                if bound_ptr is not None:
                    pointee_id, ref, extra = bound_ptr
                    # `*p = v` computes its destination from the
                    # pointer's own provenance. `*p += v` also reads
                    # the old pointee, and `**pp = v`/`***t = v`
                    # read the intermediate pointees too — the
                    # full deref-read union covers all depths.
                    self._record_read(
                        self._deref_read_deps(
                            ref.binding_id, params, locals_
                        )
                        if extra or compound
                        else self._pointer_deps(
                            ref.binding_id, params, locals_
                        )
                    )
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
                # `fs[i] = f` — an element store into a bound
                # func-element container (`fs := []func(){…}` or
                # `fm := lib.Mk(x)`): the container's conflated slot
                # accumulates the stored value's deps like a
                # composite's continuing set, the index evaluates
                # like a write's, and the stored value's func records
                # union into the container's below — a `fs[k]()` call
                # resolves every element through the one slot. A
                # param container's elements live in caller memory —
                # that external mutation stays closed here.
                func_elem_lhs = self._func_elem_index_target(
                    lhs, locals_
                )
                if func_elem_lhs is not None:
                    ref, index, inner_index = func_elem_lhs
                    # Go evaluates `fm[k()][i()]` outer index first —
                    # `inner_index` names `k()`, `index` names `i()`.
                    for idx_node in (inner_index, index):
                        if (
                            idx_node is not None
                            and idx_node.type not in (_INDEX_LITERALS)
                        ):
                            self._record_read(
                                self.expression(
                                    idx_node, fn, params, locals_,
                                    transfers, count, 0,
                                )
                            )
                    refs.append((ref, True, False))
                    func_elem_targets.add(len(refs) - 1)
                    elem_holder_ids = self._func_elem_sharers(
                        ref.binding_id
                    )
                    if inner_index is not None:
                        # `fm[k][i] = …` — only the slot `k`
                        # initialized from a donor aliases it
                        # (`fm := [][]func{fs}`: slot 0 does, a
                        # fresh `fm[1]` does not), so the write
                        # reaches the matching donors' groups, not
                        # every name the root ever shared.
                        for donor_id in self._func_elem_slot_donors(
                            ref.binding_id, inner_index
                        ):
                            elem_holder_ids |= {
                                donor_id
                            } | self._func_elem_sharers(donor_id)
                    func_elem_holders[len(refs) - 1] = frozenset(
                        elem_holder_ids
                    )
                    continue
                raise _Unsupported("unsupported_statement", _span(lhs))
            # Go assignments run in two phases — destination operands
            # (pointer indirections and index expressions) and every
            # RHS evaluate against the pre-state before any store
            # lands — so the destination reads and identifier-RHS
            # pointer provenance snapshot BEFORE `values` evaluates:
            # `p, p.V = q, 0` resolves `p.V` against the OLD `p`, and
            # `p, r = q, p` carries p's old pointer, not the store's.
            dest_reads: list = []
            rhs_ptrs: list = []
            for i, r in enumerate(refs):
                tgt = r[0] if isinstance(r, tuple) else r
                bcast = (
                    isinstance(r, tuple)
                    and len(r) >= 3
                    and bool(r[2])
                )
                nested_tgt = (
                    isinstance(r, tuple)
                    and len(r) == 4
                    and bool(r[3])
                )
                dest = None
                if (
                    tgt is not None
                    and tgt is not _ALIAS_FOLD
                ):
                    if compound:
                        # `x op= e` reads the slot's old contents; a
                        # bound-pointer target (`p.V += v`) reads its
                        # pointer's provenance plus the element's
                        # recorded contents — never the folds in the
                        # pointer slot itself.
                        if bcast:
                            dest = self._pointer_deps(
                                tgt.binding_id, params, locals_
                            ) | self.indirect_writes
                        else:
                            dest = locals_.get(
                                tgt.binding_id,
                                frozenset({params[tgt.binding_id]})
                                if tgt.binding_id in params
                                else frozenset(),
                            )
                    elif bcast:
                        # A plain bound-pointer store (`p.V = v`)
                        # reads only the pointer's provenance — the
                        # pointee contents folded into `locals_[p]`
                        # by earlier writes are not the pointer. A
                        # nested store (`p.Next.V = v`) also reads
                        # the traversed pointer field's contents —
                        # the indirect stores its value may be.
                        dest = self._pointer_deps(
                            tgt.binding_id, params, locals_
                        )
                        if nested_tgt:
                            dest = dest | self.indirect_writes
                    elif isinstance(r, tuple):
                        # A local-composite destination (`st.V = v`)
                        # merges the RHS into the binding's
                        # continuing set — the merge reads the old
                        # contents like `st.V += v` does.
                        dest = locals_.get(
                            tgt.binding_id,
                            frozenset({params[tgt.binding_id]})
                            if tgt.binding_id in params
                            else frozenset(),
                        )
                dest_reads.append(dest)
                if (
                    len(rights) == len(refs)
                    and rights[i].type == "identifier"
                ):
                    src_ref = self.references.get(
                        self.node_key(rights[i])
                    )
                    rhs_ptrs.append(
                        self._pointer_deps(
                            src_ref.binding_id, params, locals_
                        )
                        if src_ref is not None
                        else None
                    )
                else:
                    rhs_ptrs.append(None)
            # Tuple assignment is parallel: every RHS evaluates against the
            # pre-state before any store lands, so `x, y = y, x` swaps each
            # name's original dependencies. `x, y = lib.F(a)` unpacks one
            # multi-valued imported call into every LHS.
            # The function-value record maps snapshot BEFORE the RHS
            # evaluation too — a literal RHS records its own captures
            # under the name it binds during eval, so `f, g = func(){…},
            # f` must read `f`'s OLD records, not the fresh literal's.
            captures_before = dict(self.closure_captures)
            pointee_before = set(self.pointee_closures)
            aliases_before = dict(self.func_aliases)
            opaque_before = set(self.opaque_callees)
            mv_before = dict(self.bound_method_values)
            mv_deps_before = dict(self.bound_method_receiver_deps)
            writes_before = dict(self.closure_writes)
            star_before = set(self.closure_star_writes)
            calls_before = set(self.closure_inner_calls)
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
            # Func-element append operands also resolve against the
            # post-eval state: `a, c = append(b, z), append(a, z)`
            # reads `a`'s backing BEFORE `a`'s own store, so the
            # second append's records/sharers must come from these
            # snapshots, not the live maps earlier stores rewrote.
            # The stored map keys' deps join the external-write set
            # only now — the store lands after every RHS read.
            self.indirect_writes |= pending_map_key_deps
            captures_after_eval = dict(self.closure_captures)
            writes_after_eval = dict(self.closure_writes)
            star_after_eval = set(self.closure_star_writes)
            calls_after_eval = set(self.closure_inner_calls)
            # Backing tokens resolve against the pre-state too —
            # `a, b = d, a` copies the array `a` named at eval
            # time, not the one `a`'s own store redirected it to.
            tokens_after_eval = dict(self._func_elem_tokens)
            # Eval-time backing classes derive from per-name token
            # sets, not edge components: two backings never merge
            # when a conditional reseat unions their edges. Index
            # names by token and union the carriers of each token
            # the name holds — linear in the token count, and only
            # built when the statement can touch tracked func
            # elements (earlier versions rebuilt the component
            # partition per assignment, quadratically in aliases).
            func_elem_eval_class: dict[str, frozenset[str]] = {}
            if func_elem_targets or self._func_elem_tokens:
                _by_token: dict[str, set[str]] = {}
                for _n, _ts in self._func_elem_tokens.items():
                    for _t in _ts:
                        _by_token.setdefault(_t, set()).add(_n)
                for _n in set(self._func_elem_tokens) | set(_by_token):
                    _cls = {_n}
                    for _t in self._func_elem_eval_tokens(_n):
                        _cls |= _by_token.get(_t, set())
                    func_elem_eval_class[_n] = frozenset(_cls)
            # Channel alias targets resolve against the pre-state
            # too — `ch2, ch3 = ch3, ch2` swaps the queues, so each
            # RHS's root must be read before any element's store
            # updates `chan_aliases`.
            chan_alias_targets = [
                (
                    self._chan_alias_target(rights[i], locals_, params)
                    if len(lefts) == len(rights)
                    else None
                )
                for i in range(len(refs))
            ]
            # `a, b = b, g(a)` — passthrough reseats resolve against
            # the pre-state too: `g(a)` hands back the queue `a`
            # named BEFORE `a`'s own store redirects it. A
            # multi-result call (`ch, n = g(q)`) shares one RHS
            # node — the per-slot probe resolves this name's
            # position.
            call_result_targets = [
                (
                    self._chan_result_passthrough(
                        rights[i], locals_, params
                    )
                    if len(lefts) == len(rights)
                    and self._chan_result_call(rights[i]) is not None
                    else (
                        self._chan_result_passthrough(
                            rights[0], locals_, params, i
                        )
                        if len(rights) == 1
                        and len(lefts) > 1
                        else None
                    )
                )
                for i in range(len(refs))
            ]
            # A `p.C = rhs` field store's queue tokens resolve
            # against the pre-state too — `a, p.C = b, a` must
            # record the queue `a` named BEFORE `a`'s store, not
            # the one the reseat redirects it to.
            field_chan_tokens = {
                i: self._chan_queue_tokens(rights[i], locals_, params)
                for i in field_chan_lhs
                if len(lefts) == len(rights) and i < len(rights)
            }
            for i, (ref, value) in enumerate(zip(refs, values)):
                if ref is None:
                    if i in chan_write_targets:
                        # `GC = ch` — the RHS read evaluated to the
                        # queue's contents; reseating the external
                        # operand to it broadcasts those contents so
                        # `<-GC`/`range GC` reads observe them. The
                        # transfer `_record_package_write` already
                        # emitted keeps `effects` honest about the
                        # untracked reseat itself.
                        self.indirect_writes |= value
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
                        esc = self.bindings.get(escaped_id)
                        if (
                            esc is not None
                            and esc.type.kind == "pointer"
                        ):
                            # The store may have reseated the escaped
                            # pointer itself — its provenance gains
                            # the written deps too.
                            self._ptr_deps[escaped_id] = (
                                self._pointer_deps(
                                    escaped_id, params, locals_
                                )
                                | value
                            )
                    continue
                accumulating = compound
                broadcast = False
                if isinstance(ref, tuple):
                    # A `t.f = v` opaque write target: the pointee's
                    # contents gain the RHS's dependencies on top of
                    # whatever they already tracked. A bound-pointer
                    # base marks the tuple so the store also reaches
                    # `indirect_writes` — other aliased pointers'
                    # field reads observe it.
                    broadcast = len(ref) >= 3 and ref[2]
                    ref, accumulating = ref[0], ref[1]
                if accumulating:
                    # `x op= e` reads the old value too — the result unions
                    # the binding's current dependencies with the RHS's.
                    if ref.binding_id in locals_:
                        old = locals_[ref.binding_id]
                    else:
                        old = frozenset({params[ref.binding_id]})
                    if dest_reads[i] is not None:
                        # An `op=` assignment reads the old value,
                        # a bound-pointer target (`p.V = v`,
                        # `*p = v`) reads the pointer's pre-state
                        # provenance to compute the destination —
                        # snapshotted in `dest_reads` because `p,
                        # p.V = q, 0` resolves `p.V` against the OLD
                        # `p` and `p.V = x; p.V = 0` must not read
                        # x's fold as the pointer — and a local
                        # composite (`st.V = v`) reads its old
                        # contents: the merge carries them into the
                        # binding's continuing set.
                        self._record_read(dest_reads[i])
                    value = old | value
                if not compound and self._is_chan_binding(ref.binding_id):
                    # `ch2 = ch` redirects the alias — sends through
                    # ch2 now land in the new source's dep set, a
                    # `ch2 = make(chan)` RHS re-creates the queue so
                    # the alias drops, and `ch = g()` where `g`
                    # declares a single scalar `chan` result reseats
                    # the name to the callee-produced queue (the same
                    # hand-off `ch := g()` admits). A
                    # tuple-of-different-width (`ch2, _ = <-q`), a
                    # receive, a non-`chan` call result or a
                    # non-scalar element produce a queue the
                    # conflated dep set cannot model — all stay
                    # closed.
                    chan_alias = chan_alias_targets[i]
                    fresh_make = (
                        len(lefts) == len(rights)
                        and self._is_make_chan_call(rights[i])
                    )
                    call_result = (
                        len(lefts) == len(rights)
                        and self._chan_result_call(rights[i])
                        is not None
                    ) or (
                        len(rights) == 1
                        and len(lefts) > 1
                        and self._chan_result_call_at(rights[0], i)
                        is not None
                    )
                    chan_chan_result = self._chan_chan_fact(
                        self.bindings[ref.binding_id].type
                    ) and (
                        (
                            len(lefts) == len(rights)
                            and self._chan_result_call(
                                rights[i], self._chan_chan_fact
                            )
                            is not None
                        ) or (
                            len(rights) == 1
                            and len(lefts) > 1
                            and self._chan_result_call_at(
                                rights[0], i, self._chan_chan_fact
                            )
                            is not None
                        )
                    )
                    if chan_chan_result:
                        # `cc = G()` reseats a `chan chan` name to the
                        # callee-produced external queue like `cc :=
                        # G()` binds it — the name is already modelled
                        # externally (parameter or callee result), so
                        # the slot just gains the call's folded deps
                        # whether or not the store can be skipped.
                        self.chan_aliases.pop(ref.binding_id, None)
                        self.external_chan_locals.add(
                            ref.binding_id
                        )
                        base = locals_.get(ref.binding_id)
                        if (
                            base is None
                            and ref.binding_id in params
                        ):
                            base = frozenset(
                                {params[ref.binding_id]}
                            )
                        locals_[ref.binding_id] = (
                            base or frozenset()
                        ) | value
                        continue
                    chan_recv = (
                        (
                            len(lefts) == len(rights)
                            and self._chan_chan_receive(
                                rights[i], params
                            )
                        )
                        or (
                            len(rights) == 1
                            and len(lefts) > 1
                            and self._is_chan_recv(
                                rights[0], len(lefts)
                            )
                            and self._chan_chan_receive(
                                rights[0], params
                            )
                        )
                    )
                    if not self._scalar_chan_binding(ref.binding_id) or (
                        not fresh_make
                        and chan_alias is None
                        and not call_result
                        and not chan_recv
                    ):
                        raise _Unsupported(
                            "binding_unavailable", _span(node)
                        )
                    if chan_recv:
                        # `c = <-cc` / `c, _ = <-cc` — the received
                        # channel reseats the name to an external
                        # queue like `c := <-cc` binds it. The slot
                        # unions the old contents with the received
                        # deps, so a maybe-skipped store keeps both
                        # queue meanings' coverage.
                        old_queue = frozenset()
                        if conditional or self._may_skip > 0:
                            # A maybe-skipped `c = <-cc` can leave
                            # `c` meaning EITHER its aliased queue
                            # or the received one — externalize the
                            # old root too and merge its contents
                            # into the slot like the conditional
                            # rebind arm below.
                            root_before = self._chan_root(
                                ref.binding_id
                            )
                            old_queue = locals_.get(root_before)
                            if (
                                old_queue is None
                                and root_before in params
                            ):
                                old_queue = frozenset(
                                    {params[root_before]}
                                )
                            if root_before != ref.binding_id:
                                self.external_chan_locals.add(
                                    root_before
                                )
                        self.chan_aliases.pop(ref.binding_id, None)
                        self.external_chan_locals.add(
                            ref.binding_id
                        )
                        base = locals_.get(ref.binding_id)
                        if (
                            base is None
                            and ref.binding_id in params
                        ):
                            base = frozenset(
                                {params[ref.binding_id]}
                            )
                        locals_[ref.binding_id] = (
                            (base or frozenset())
                            | old_queue
                            | value
                        )
                        continue
                    if conditional or self._may_skip > 0:
                        # A maybe-skipped rebind can leave the name
                        # meaning EITHER its old queue or the new
                        # one, and the conflated dep set has no
                        # "either queue" union. A fresh `make` on an
                        # unaliased name admits as before — the
                        # slot's dep union covers both queues —
                        # since every name resolving to it converges
                        # on the same slot. Any other shape (an alias
                        # reseat `ch = q`, a passthrough `ch = g(q)`,
                        # an external `ch = g()`, or a `make` over a
                        # currently-aliased name) detaches the name
                        # into an external queue: its slot unions the
                        # old queue's contents with the RHS deps, and
                        # every queue it could still mean is promoted
                        # external so sends broadcast and reads union
                        # `indirect_writes` — a name that kept the
                        # old queue's identity under another alias
                        # (`z := t_old` before `ch = q`) still sees
                        # writes the untaken path delivered there.
                        if fresh_make and (
                            ref.binding_id not in self.chan_aliases
                            and ref.binding_id
                            not in self.chan_aliases.values()
                        ):
                            # No alias resolves THROUGH this name and
                            # none names its slot — overwriting the
                            # slot with the fresh queue drops nothing
                            # a surviving alias still reads.
                            pass
                        else:
                            passthrough = (
                                call_result_targets[i]
                                if call_result
                                else None
                            )
                            target = (
                                chan_alias
                                if chan_alias is not None
                                else passthrough
                            )
                            if (
                                target is None
                                and not call_result
                                and not fresh_make
                            ):
                                raise _Unsupported(
                                    "binding_unavailable", _span(node)
                                )
                            if call_result:
                                # `ch = g(q)` — `g` may hand `q`'s
                                # own queue back through a local
                                # alias (`r := q; return r`) the
                                # passthrough probe cannot see, so
                                # every `chan` argument's root is a
                                # queue the result may mean: promote
                                # each to external and union its
                                # contents into the name's slot like
                                # `target` below.
                                value = value | (
                                    self._promote_chan_call_args(
                                        rights[i]
                                        if len(lefts) == len(rights)
                                        else rights[0],
                                        ref.binding_id,
                                        locals_,
                                        params,
                                    )
                                )
                            root_before = self._chan_root(
                                ref.binding_id
                            )
                            old_queue = locals_.get(root_before)
                            if (
                                old_queue is None
                                and root_before in params
                            ):
                                old_queue = frozenset(
                                    {params[root_before]}
                                )
                            self.chan_aliases.pop(
                                ref.binding_id, None
                            )
                            self.external_chan_locals.add(
                                ref.binding_id
                            )
                            if root_before != ref.binding_id:
                                self.external_chan_locals.add(
                                    root_before
                                )
                            if (
                                target is not None
                                and target.id != ref.binding_id
                            ):
                                self.external_chan_locals.add(
                                    target.id
                                )
                            base = locals_.get(ref.binding_id)
                            if (
                                base is None
                                and ref.binding_id in params
                            ):
                                base = frozenset(
                                    {params[ref.binding_id]}
                                )
                            locals_[ref.binding_id] = (
                                (base or frozenset())
                                | (old_queue or frozenset())
                                | value
                            )
                            continue
                    if chan_alias is not None:
                        self.chan_aliases[ref.binding_id] = chan_alias.id
                        # A reseat redirects only the name — the
                        # `_store` below would overwrite
                        # `locals_[ref.binding_id]`, but that slot
                        # IS the old queue's contents, now owned by
                        # whoever aliases it (`a <- x; a, b = b, a`
                        # must keep x reachable through `b`).
                        continue
                    elif call_result:
                        # `ch = g()` reseats the name: a passthrough
                        # callee hands the argument's queue back so
                        # `ch` aliases it like `ch = q`, otherwise
                        # the name keeps an external queue of its
                        # own and drops any prior alias.
                        passthrough = call_result_targets[i]
                        if passthrough is not None:
                            self.chan_aliases[ref.binding_id] = (
                                passthrough.id
                            )
                        else:
                            self.chan_aliases.pop(
                                ref.binding_id, None
                            )
                            self.external_chan_locals.add(
                                ref.binding_id
                            )
                            # The slot keeps the old queue's
                            # contents (other aliases still read
                            # them) AND the callee-produced
                            # dependencies — `g(x)`'s result can
                            # carry `x`, so `<-ch` must see it. The
                            # callee may hand a `chan` argument's
                            # own queue back through a local alias
                            # the probe cannot see (`r := q; return
                            # r, 0`), so those roots go external and
                            # their contents fold in like the
                            # conditional arm above.
                            value = value | (
                                self._promote_chan_call_args(
                                    rights[i]
                                    if len(lefts) == len(rights)
                                    else rights[0],
                                    ref.binding_id,
                                    locals_,
                                    params,
                                )
                            )
                            base = locals_.get(ref.binding_id)
                            if (
                                base is None
                                and ref.binding_id in params
                            ):
                                base = frozenset(
                                    {params[ref.binding_id]}
                                )
                            locals_[ref.binding_id] = (
                                base or frozenset()
                            ) | value
                            # `ch = lib.G(q)` — an imported callee
                            # may hand `q`'s queue back, so every
                            # `chan` argument joins the external
                            # model and its contents seed the slot.
                            for arg_root in (
                                self._imported_chan_result_args(
                                    rights[i]
                                    if len(lefts) == len(rights)
                                    else rights[0],
                                    locals_,
                                    params,
                                    i if len(rights) == 1 else 0,
                                )
                            ):
                                self.external_chan_locals.add(
                                    arg_root
                                )
                                locals_[ref.binding_id] |= (
                                    locals_.get(
                                        arg_root,
                                        (
                                            frozenset(
                                                {params[arg_root]}
                                            )
                                            if arg_root in params
                                            else frozenset()
                                        ),
                                    )
                                )
                        continue
                    elif fresh_make:
                        self.chan_aliases.pop(ref.binding_id, None)
                        # A `make` reseat leaves earlier aliases
                        # pointing at the OLD queue — it still
                        # exists for them (`ch = q; q = make(...)`).
                        # Copy the old queue's contents onto each
                        # alias's own slot and detach it: `<-ch`
                        # keeps the queued sends while `<-q` reads
                        # only the fresh queue.
                        for alias_id, target in list(
                            self.chan_aliases.items()
                        ):
                            if target != ref.binding_id:
                                continue
                            del self.chan_aliases[alias_id]
                            old_queue = locals_.get(ref.binding_id)
                            if (
                                old_queue is None
                                and ref.binding_id in params
                            ):
                                old_queue = frozenset(
                                    {params[ref.binding_id]}
                                )
                            alias_slot = locals_.get(alias_id)
                            if (
                                alias_slot is None
                                and alias_id in params
                            ):
                                alias_slot = frozenset(
                                    {params[alias_id]}
                                )
                            locals_[alias_id] = (
                                alias_slot or frozenset()
                            ) | (old_queue or frozenset())
                if not compound and ref is not None:
                    bound = self.bindings.get(ref.binding_id)
                    if bound is not None and (
                        bound.type.kind == "function"
                        or self._func_elem_collection(bound.type)
                        or self._func_elem_nested_collection(bound.type)
                    ):
                        # `f = mk(ch)` — like the declaration
                        # forms, the returned closure may capture
                        # the call's `chan` arguments.
                        value = value | self._func_result_chan_args(
                            (
                                rights[i]
                                if len(lefts) == len(rights)
                                else rights[0]
                            ),
                            locals_,
                            params,
                        )
                if not accumulating:
                    # A plain store replaces what the pointer itself
                    # depends on — pointee folds stay in `locals_`
                    # and never enter `_ptr_deps`. An identifier RHS
                    # carries the source's own pointer provenance
                    # (`p = q`), not its folded slot; a conditional
                    # store unions the pre-state like `_store` does.
                    ptr_new = (
                        rhs_ptrs[i]
                        if rhs_ptrs[i] is not None
                        else value
                    )
                    if conditional:
                        ptr_new = (
                            self._pointer_deps(
                                ref.binding_id, params, locals_
                            )
                            | ptr_new
                        )
                    self._ptr_deps[ref.binding_id] = ptr_new
                # Reassignment replaces the binding's dependencies; it never
                # declares a new variable. Inside a branch the caller's join
                # unions the new value back as a may-assignment.
                self._store(
                    locals_, params, ref.binding_id, value, conditional,
                )
                if broadcast:
                    self.indirect_writes |= value
                member = field_chan_lhs.get(i)
                if (
                    member is not None
                    and i < len(rights)
                    and len(lefts) == len(rights)
                ):
                    tokens = field_chan_tokens.get(i)
                    if tokens is not None:
                        # `p.C = ch` — the field may now name ch's
                        # queue. Union into the member's may-set
                        # (a conditional store leaves the previous
                        # queue a candidate, so never replace).
                        self.field_chan_queues[member.id] = (
                            self.field_chan_queues.get(
                                member.id, frozenset()
                            )
                            | tokens
                        )
                # An element store through one name lands in every
                # name sharing the backing (`fs2 := fs`) — the
                # stored value's deps join each sharer's set like
                # the container's own store did.
                if i in func_elem_targets:
                    # Resolution-time sharers plus landing-time
                    # group — a parallel reseat (`a, a[0] = b, f`)
                    # detaches `a` from the aliases the write still
                    # reaches, and a parallel copy (`a2, a[0] = a,
                    # f`) shares `a` only after the LHS resolved.
                    elem_holders = (
                        func_elem_holders.get(
                            i, frozenset({ref.binding_id})
                        )
                        | self._func_elem_sharers(ref.binding_id)
                    ) - func_elem_reseated | {ref.binding_id}
                    for holder_id in elem_holders:
                        # Accumulate like the container's own
                        # element store — replacing would wipe the
                        # deps `append` elements already landed.
                        self._store(
                            locals_, params, holder_id, value, True
                        )
                # `fs[i] = f` — a store into a func-element
                # container unions the stored value's records into
                # the container's, like an element inside
                # `fs := []func(){f}`. The pre-state snapshots make
                # `f, fs[i] = g, f` adopt f's OLD records — the
                # parallel store's write to f lands after. A
                # selector RHS (`fs[i] = s.f`) names the FIELD's
                # member — the whole-selector reference resolves to
                # the operand, so the field's own record lookup is
                # what finds a literal stored into `s.f` earlier.
                if (
                    i in func_elem_targets
                    and len(lefts) == len(rights)
                    and rights[i].type
                    in {"identifier", "selector_expression"}
                ):
                    if rights[i].type == "selector_expression":
                        field = rights[i].child_by_field_name("field")
                        field_ref = (
                            self.references.get(self.node_key(field))
                            if field is not None
                            else None
                        )
                        member = self._field_identity(field_ref)
                        src_id = (
                            member.id if member is not None else None
                        )
                    else:
                        src_ref = self.references.get(
                            self.node_key(rights[i])
                        )
                        src_id = (
                            src_ref.binding_id
                            if src_ref is not None
                            else None
                        )
                    if (
                        src_id is not None
                        and src_id != ref.binding_id
                    ):
                        # Names sharing the container's backing
                        # (`fs2 := fs`) read the same elements —
                        # the store lands in every sharer's records.
                        for holder_id in elem_holders:
                            if src_id in captures_before:
                                self.closure_captures[holder_id] = (
                                    self.closure_captures.get(
                                        holder_id, frozenset()
                                    )
                                    | captures_before[src_id]
                                )
                            if src_id in writes_before:
                                self.closure_writes[holder_id] = (
                                    self.closure_writes.get(
                                        holder_id, frozenset()
                                    )
                                    | writes_before[src_id]
                                )
                            if src_id in star_before:
                                self.closure_star_writes.add(
                                    holder_id
                                )
                            if src_id in calls_before:
                                self.closure_inner_calls.add(
                                    holder_id
                                )
                # `fs2[i] = func(){…}` — the literal recorded its
                # captures under this name during RHS eval; names
                # sharing the backing hold the same elements, so
                # the fresh records union into each sharer too.
                if (
                    i in func_elem_targets
                    and len(lefts) == len(rights)
                    and rights[i].type == "func_literal"
                ):
                    for holder_id in elem_holders:
                        self._adopt_element_records(
                            ref.binding_id, holder_id
                        )
                # `h2 = h` — an assignment copy propagates the
                # closure's capture record like `h2 := h` does; a
                # non-closure RHS clears a stale record on the name.
                if (
                    not compound
                    and i not in func_elem_targets
                    and len(lefts) == len(rights)
                    and rights[i].type == "identifier"
                ):
                    src_ref = self.references.get(
                        self.node_key(rights[i])
                    )
                    src_id = (
                        src_ref.binding_id if src_ref is not None else None
                    )
                    tgt_bound = self.bindings.get(ref.binding_id)
                    if (
                        not conditional
                        and self._may_skip == 0
                        and tgt_bound is not None
                        and (
                            self._func_elem_collection(tgt_bound.type)
                            or self._func_elem_nested_collection(
                                tgt_bound.type
                            )
                        )
                        and (
                            src_id is None
                            or self._func_elem_eval_tokens(src_id)
                            != self._func_elem_eval_tokens(
                                ref.binding_id
                            )
                        )
                    ):
                        func_elem_reseat_backings[ref.binding_id] = (
                            func_elem_eval_class.get(
                                src_id, frozenset({src_id})
                            )
                            if src_id is not None
                            else frozenset({ref.binding_id})
                        )
                        # A definite reseat leaves the backing the
                        # name used to share — hand its element
                        # records to the remaining sharers BEFORE
                        # the copy below replaces this name's
                        # records. `a, a[0] = b, f` recorded the
                        # literal under `a` during RHS eval: that
                        # record belongs to the OLD array `a`'s
                        # sharers keep, not to `a`'s new backing.
                        # The landing is the operand's EVAL-time
                        # backing: when the name already holds
                        # exactly that (`b = b` while `b` shares
                        # `a`'s array) there is no detach — `b`
                        # stays a holder for parallel element
                        # writes. A self-copy (`a, a = d, a`)
                        # still reseats: the second `a`'s live
                        # tokens were already rewritten by the
                        # first store, so it detaches and re-lands
                        # on `a`'s eval-time backing.
                        if (
                            src_id is None
                            or tokens_after_eval.get(
                                src_id, frozenset({src_id})
                            )
                            != self._func_elem_eval_tokens(
                                ref.binding_id
                            )
                        ):
                            self._func_elem_reseat(ref.binding_id)
                            func_elem_reseated.add(ref.binding_id)
                    # A maybe-skipped copy leaves the name holding
                    # EITHER function value. When the source carries
                    # a resolvable record the union covers both
                    # candidates; when it carries none the may-set
                    # includes an unresolvable value — drop the old
                    # record too, so the call falls back to the
                    # opaque external callee model.
                    if conditional or self._may_skip > 0:
                        src_known = (
                            src_id is not None
                            and (
                                src_id in captures_before
                                or src_id in writes_before
                                or src_id in pointee_before
                                or src_id in star_before
                                or src_id in calls_before
                                or src_id in aliases_before
                                or src_id in opaque_before
                            )
                        )
                        if src_known:
                            if src_id in captures_before:
                                self.closure_captures[
                                    ref.binding_id
                                ] = (
                                    self.closure_captures.get(
                                        ref.binding_id, frozenset()
                                    )
                                    | captures_before[src_id]
                                )
                            if src_id in writes_before:
                                self.closure_writes[
                                    ref.binding_id
                                ] = (
                                    self.closure_writes.get(
                                        ref.binding_id, frozenset()
                                    )
                                    | writes_before[src_id]
                                )
                            if src_id in pointee_before:
                                self.pointee_closures.add(
                                    ref.binding_id
                                )
                            if src_id in star_before:
                                self.closure_star_writes.add(
                                    ref.binding_id
                                )
                            if src_id in calls_before:
                                self.closure_inner_calls.add(
                                    ref.binding_id
                                )
                            if (
                                src_id is not None
                                and src_id in opaque_before
                            ):
                                self.opaque_callees.add(
                                    ref.binding_id
                                )
                        else:
                            # src carries NO resolvable record — the
                            # taken path hands the name an opaque
                            # value. Keep whatever the untaken path's
                            # own alternatives described and mark the
                            # name so the external model covers both.
                            self.opaque_callees.add(ref.binding_id)
                        # A maybe-skipped `h = g` may also hand h a
                        # bound method value — keep the resolved pair
                        # only when both candidates name the SAME
                        # (method, receiver); otherwise drop to the
                        # opaque external callee model. The same
                        # (method, receiver) pair can still freeze
                        # different dep sets when the receiver was
                        # reseated between the two binds, so the kept
                        # pair unions both dep records.
                        if mv_before.get(src_id) != (
                            self.bound_method_values.get(ref.binding_id)
                        ):
                            self._drop_bound_method(
                                ref.binding_id, True
                            )
                        elif (
                            src_id is not None
                            and src_id in mv_deps_before
                        ):
                            self.bound_method_receiver_deps[
                                ref.binding_id
                            ] = self.bound_method_receiver_deps.get(
                                ref.binding_id, frozenset()
                            ) | mv_deps_before[
                                src_id
                            ]
                    else:
                        # A func-element container that stayed on
                        # its backing (a self-backing copy like
                        # `a, a[0] = b, f`) keeps the element
                        # records RHS eval just stored under it —
                        # replacing would drop the literal `f`
                        # before the `a[0]` write adopts it, and
                        # popping would erase the array's elements
                        # the name still shares.
                        elem_keep = (
                            tgt_bound is not None
                            and self._func_elem_collection(
                                tgt_bound.type
                            )
                            and ref.binding_id
                            not in func_elem_reseated
                        )
                        if (
                            src_id is not None
                            and src_id in captures_before
                        ):
                            if elem_keep:
                                self.closure_captures[
                                    ref.binding_id
                                ] = self.closure_captures.get(
                                    ref.binding_id, frozenset()
                                ) | captures_before[
                                    src_id
                                ]
                            else:
                                self.closure_captures[
                                    ref.binding_id
                                ] = captures_before[src_id]
                        elif not elem_keep:
                            self.closure_captures.pop(
                                ref.binding_id, None
                            )
                        # `g = f` where f is a bound method value
                        # copies the (method, receiver) pair AND its
                        # frozen receiver deps — read from the
                        # pre-state so `f, g = g, f` swaps like the
                        # capture maps.
                        src_mv = (
                            mv_before.get(src_id)
                            if src_id is not None
                            else None
                        )
                        if src_mv is not None:
                            self.bound_method_values[
                                ref.binding_id
                            ] = src_mv
                            if src_id in mv_deps_before:
                                self.bound_method_receiver_deps[
                                    ref.binding_id
                                ] = mv_deps_before[src_id]
                            else:
                                self.bound_method_receiver_deps.pop(
                                    ref.binding_id, None
                                )
                        elif not elem_keep:
                            self._drop_bound_method(ref.binding_id)
                        if (
                            src_id is not None
                            and src_id in pointee_before
                        ):
                            self.pointee_closures.add(ref.binding_id)
                        elif not elem_keep:
                            self.pointee_closures.discard(
                                ref.binding_id
                            )
                        if (
                            src_id is not None
                            and src_id in writes_before
                        ):
                            if elem_keep:
                                self.closure_writes[
                                    ref.binding_id
                                ] = self.closure_writes.get(
                                    ref.binding_id, frozenset()
                                ) | writes_before[
                                    src_id
                                ]
                            else:
                                self.closure_writes[
                                    ref.binding_id
                                ] = writes_before[src_id]
                        elif not elem_keep:
                            self.closure_writes.pop(
                                ref.binding_id, None
                            )
                        if (
                            src_id is not None
                            and src_id in star_before
                        ):
                            self.closure_star_writes.add(
                                ref.binding_id
                            )
                        elif not elem_keep:
                            self.closure_star_writes.discard(
                                ref.binding_id
                            )
                        if (
                            src_id is not None
                            and src_id in calls_before
                        ):
                            self.closure_inner_calls.add(
                                ref.binding_id
                            )
                        elif not elem_keep:
                            self.closure_inner_calls.discard(
                                ref.binding_id
                            )
                        if (
                            src_id is not None
                            and src_id in opaque_before
                        ):
                            self.opaque_callees.add(ref.binding_id)
                        elif not elem_keep:
                            self.opaque_callees.discard(
                                ref.binding_id
                            )
                    # `h = G` binds a declared function name; `h2 =
                    # h` inherits the alias h recorded.
                    self._propagate_func_alias(
                        ref.binding_id, src_id, aliases_before,
                        params, conditional,
                    )
                    src_bound = (
                        self.bindings.get(src_id)
                        if src_id is not None
                        else None
                    )
                    if (
                        src_bound is not None
                        and tgt_bound is not None
                        and (
                            self._func_elem_collection(
                                src_bound.type
                            )
                            or self._func_elem_nested_collection(
                                src_bound.type
                            )
                        )
                        and (
                            self._func_elem_collection(
                                tgt_bound.type
                            )
                            or self._func_elem_nested_collection(
                                tgt_bound.type
                            )
                        )
                    ):
                        # `fs2 = fs` — the copy shares the
                        # backing like `fs2 := fs`; a definite
                        # rebind first left the backing it used to
                        # share (group membership is a single
                        # backing). The backing the RHS named is
                        # the resolution-time one: `a, b = d, a`
                        # reseated `a` before this store landed,
                        # but `b` still copies the OLD array, so
                        # share against the operand's eval-time
                        # members — like the append operand below —
                        # and drop members reseated onto a
                        # different backing.
                        share_eval = (
                            func_elem_eval_class.get(
                                src_id, frozenset({src_id})
                            )
                        )
                        share_members = set(share_eval) - {ref.binding_id}
                        # Eval-time groups partition names by
                        # backing, so a reseated member stays only
                        # when it landed on THE SAME class — an
                        # intersection test fails because a name's
                        # own id can stand for two different
                        # backings across the statement
                        # (`a, c = c, b`: `a`'s landing class {c}
                        # intersects {a,b,c} without sharing `b`'s
                        # backing).
                        for member_id in set(share_members):
                            if (
                                member_id in func_elem_reseated
                                and func_elem_reseat_backings.get(
                                    member_id, set()
                                )
                                != share_eval
                            ):
                                share_members.discard(member_id)
                        for member_id in share_members:
                            self._func_elem_share(
                                ref.binding_id,
                                member_id,
                                tokens_after_eval.get(
                                    member_id, frozenset({member_id})
                                ),
                            )
                elif (
                    not compound
                    and i not in func_elem_targets
                    and len(lefts) == len(rights)
                    and rights[i].type == "selector_expression"
                    and ref is not None
                ):
                    # `f = s.M` — rebind to a method value; a
                    # conditional rebind keeps the old alternative, so
                    # pop instead. A func-element index store is not a
                    # name rebind — the adoption above already unioned
                    # the selector's records into the container's.
                    mv = self._method_value_parts(rights[i])
                    if mv is not None and not (
                        conditional or self._may_skip > 0
                    ):
                        # A non-identifier RHS replaces whatever
                        # callee the name held — stale captures
                        # would resolve the call to only the old
                        # alternative. Clear first, then record the
                        # new (method, receiver) pair.
                        self._drop_func_value_records(ref.binding_id)
                        self._record_bound_method(
                            ref.binding_id, mv, params, locals_,
                        )
                    else:
                        # A conditional rebind keeps the untaken
                        # path's old callee live — the name resolves
                        # opaquely, with the old value's write
                        # targets and captures escaped so the call
                        # still folds their deps back in.
                        self._drop_func_value_records(
                            ref.binding_id,
                            conditional or self._may_skip > 0,
                        )
                elif (
                    not compound
                    and ref is not None
                    and i not in func_elem_targets
                ):
                    self._drop_bound_method(
                        ref.binding_id,
                        conditional or self._may_skip > 0,
                    )
                    self.func_aliases.pop(ref.binding_id, None)
                    rhs_node = (
                        rights[i]
                        if len(lefts) == len(rights)
                        else rights[0]
                    )
                    ref_bound = self.bindings.get(ref.binding_id)
                    append_cont = (
                        self._func_elem_append_target(
                            rhs_node, locals_
                        )
                        if ref_bound is not None
                        and self._func_elem_collection(ref_bound.type)
                        else None
                    )
                    if append_cont is not None:
                        # `fs = append(fs, f)` / `fs2 = append(fs,
                        # f)` — the element records the builtin
                        # branch adopted during RHS eval stand;
                        # the result may reuse the argument's
                        # array, so the name joins its group and
                        # sees the container's elements. A
                        # different container first detaches from
                        # the backing it used to share.
                        if (
                            not conditional
                            and self._may_skip == 0
                            and ref.binding_id != append_cont
                        ):
                            self._func_elem_reseat(ref.binding_id)
                            func_elem_reseated.add(ref.binding_id)
                            func_elem_reseat_backings[
                                ref.binding_id
                            ] = set(
                                func_elem_eval_class.get(
                                    append_cont,
                                    frozenset({append_cont}),
                                )
                            )
                            # The name points at the append result's
                            # backing now — its own old elements stay
                            # reachable only through the sharers the
                            # reseat handed them to, so the stale
                            # records drop before `b`'s arrive.
                            self.closure_captures.pop(
                                ref.binding_id, None
                            )
                            self.closure_writes.pop(
                                ref.binding_id, None
                            )
                            self.closure_star_writes.discard(
                                ref.binding_id
                            )
                            self.closure_inner_calls.discard(
                                ref.binding_id
                            )
                        # The operand's backing resolved before any
                        # store in this statement — a parallel
                        # `a = append(b, z)` reseat redirected `a`'s
                        # name, but `append(a, z)` still reads the
                        # old backing's elements and group.
                        append_members = (
                            set(
                                func_elem_eval_class.get(
                                    append_cont,
                                    frozenset({append_cont}),
                                )
                            )
                        ) - {ref.binding_id}
                        # A member reseated in this statement only
                        # leaves the operand's backing when the
                        # backing it reseated ONTO is a different
                        # one: `a, c = a2, append(a, z)` reseats `a`
                        # onto `a2`'s — the same — backing, so `a`'s
                        # later element writes still land in `c`;
                        # `b` in `a, b, c = d, a, append(a, z)`
                        # reseats onto the operand's own backing.
                        append_eval = set(
                            func_elem_eval_class.get(
                                append_cont,
                                frozenset({append_cont}),
                            )
                        )
                        # Same class-equality rule as the copy
                        # path: `a, b = make(…), append(a, z)`
                        # reseats `a` onto a fresh backing ({}, not
                        # the operand's class) so `a` must leave.
                        for member_id in set(append_members):
                            if (
                                member_id in func_elem_reseated
                                and func_elem_reseat_backings.get(
                                    member_id, set()
                                )
                                != append_eval
                            ):
                                append_members.discard(member_id)
                        for member_id in append_members:
                            self._func_elem_share(
                                ref.binding_id,
                                member_id,
                                tokens_after_eval.get(
                                    member_id, frozenset({member_id})
                                ),
                            )
                        captured = captures_after_eval.get(
                            append_cont
                        )
                        if captured:
                            self.closure_captures[
                                ref.binding_id
                            ] = (
                                self.closure_captures.get(
                                    ref.binding_id, frozenset()
                                )
                                | captured
                            )
                        writes = writes_after_eval.get(append_cont)
                        if writes:
                            self.closure_writes[ref.binding_id] = (
                                self.closure_writes.get(
                                    ref.binding_id, frozenset()
                                )
                                | writes
                            )
                        if append_cont in star_after_eval:
                            self.closure_star_writes.add(
                                ref.binding_id
                            )
                        if append_cont in calls_after_eval:
                            self.closure_inner_calls.add(
                                ref.binding_id
                            )
                    elif (
                        (
                            len(lefts) != len(rights)
                            or rights[i].type != "func_literal"
                        )
                        and not self._is_func_elem_composite(
                            rhs_node,
                            ref.binding_id,
                        )
                    ):
                        # A non-literal RHS leaves only stale records
                        # behind; a literal's fresh records stand.
                        # Under a conditional rebind the untaken path
                        # keeps the old value — mark the name opaque
                        # and keep its records so the call folds that
                        # alternative with CURRENT deps; an
                        # unconditional store loses the alternative
                        # outright, so the records drop with the mark.
                        if conditional or self._may_skip > 0:
                            self.opaque_callees.add(ref.binding_id)
                        else:
                            # The name reseats to a value that does
                            # not share the backing — its element
                            # records transfer to the names that
                            # still share it before the group drops.
                            self._func_elem_reseat(ref.binding_id)
                            func_elem_reseated.add(ref.binding_id)
                            # Fresh backing — empty landing class,
                            # distinct from any eval-time one.
                            func_elem_reseat_backings[
                                ref.binding_id
                            ] = set()
                            self.opaque_callees.discard(
                                ref.binding_id
                            )
                            self.closure_captures.pop(
                                ref.binding_id, None
                            )
                            self.pointee_closures.discard(
                                ref.binding_id
                            )
                            self.closure_writes.pop(
                                ref.binding_id, None
                            )
                            self.closure_star_writes.discard(
                                ref.binding_id
                            )
                            self.closure_inner_calls.discard(
                                ref.binding_id
                            )
                    elif self._is_func_elem_composite(
                        (
                            rights[i]
                            if len(lefts) == len(rights)
                            else rights[0]
                        ),
                        ref.binding_id,
                    ):
                        # `fs = []func(){…}` — a composite RHS on
                        # an existing container keeps its element
                        # records and adopts identifier elements'.
                        # A definite reseat detaches from the old
                        # backing first so its elements reach the
                        # names still sharing it, not the name.
                        if not conditional and self._may_skip == 0:
                            self._func_elem_reseat(
                                ref.binding_id,
                                (
                                    captures_before,
                                    writes_before,
                                    star_before,
                                    calls_before,
                                ),
                            )
                            func_elem_reseated.add(ref.binding_id)
                            func_elem_reseat_backings[
                                ref.binding_id
                            ] = set()
                        self._adopt_container_element_records(
                            (
                                rights[i]
                                if len(lefts) == len(rights)
                                else rights[0]
                            ),
                            ref.binding_id,
                        )
                elif i not in func_elem_targets:
                    # `h = (f)` / `h = f()` — a non-identifier RHS
                    # leaves the name holding a value the alias
                    # cannot resolve; an unconditional store loses
                    # the target outright and a maybe-skipped one
                    # leaves it path-dependent, so the records drop
                    # either way — conditionally escaping the old
                    # value's write targets and captures first. A
                    # func-element index store keeps the container's
                    # unioned records the adoption above built.
                    self._drop_func_value_records(
                        ref.binding_id,
                        conditional or self._may_skip > 0,
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
            ptr_scope = dict(self._ptr_deps)
            update = None
            # (elem binding id, seed deps, local channel id | None).
            range_elem = None
            # (key binding id, seed deps, None, re-join escaped).
            range_key = None
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
                container_var = (
                    self._package_container_var(right)
                    if right is not None and member is None
                    else None
                )
                bound = None
                package_pointee = None
                range_ident = None
                computed = None
                if (
                    right is not None
                    and member is None
                    and container_var is None
                ):
                    # `for range *p` / `for range p` — a bound
                    # pointer whose pointee is a container, or a
                    # package-level pointer var's, iterates caller
                    # memory the way `(*p)[i]`/`(*GP)[i]` reads it.
                    cur = right
                    while (
                        cur is not None
                        and cur.type == "parenthesized_expression"
                    ):
                        cur = next(
                            (
                                c
                                for c in cur.named_children
                                if c.type != "comment"
                            ),
                            None,
                        )
                    sugar = False
                    call_operand = None
                    if (
                        cur is not None
                        and cur.type == "unary_expression"
                    ):
                        operator = cur.child_by_field_name("operator")
                        sub = cur.child_by_field_name("operand")
                        while (
                            sub is not None
                            and sub.type == "parenthesized_expression"
                        ):
                            sub = next(
                                (
                                    c
                                    for c in sub.named_children
                                    if c.type != "comment"
                                ),
                                None,
                            )
                        if (
                            operator is not None
                            and operator.text == b"*"
                            and sub is not None
                        ):
                            if sub.type == "identifier":
                                range_ident = sub
                            elif sub.type == "call_expression":
                                call_operand = sub
                    elif cur is not None and cur.type == "identifier":
                        range_ident = cur
                        sugar = True
                    elif cur is not None and cur.type == "call_expression":
                        call_operand = cur
                        sugar = True
                    if call_operand is not None:
                        # `for range *G()` / `for range G()` — the
                        # container lives in the memory the callee's
                        # result points at (or IS, for a direct
                        # container result), so the elements iterate
                        # caller-observable memory like `(*p)[i]`.
                        # An imported callee's member record also
                        # declares `result_types` even when the
                        # composite result keeps the call
                        # `external_or_bodyless`, so `for range
                        # lib.G(a)` admits on the same shape.
                        call = self.calls.get(self.node_key(call_operand))
                        call_member = None
                        if (
                            call is not None
                            and call.owner == fn.binding_id
                            and call.kind
                            in ("direct_import", "external_or_bodyless")
                        ):
                            callee = call_operand.child_by_field_name(
                                "function"
                            )
                            while (
                                callee is not None
                                and callee.type
                                == "parenthesized_expression"
                            ):
                                callee = next(
                                    (
                                        c
                                        for c in callee.named_children
                                        if c.type != "comment"
                                    ),
                                    None,
                                )
                            if (
                                callee is not None
                                and callee.type == "selector_expression"
                            ):
                                call_member = self._package_member(callee)
                            _, rf = self._call_result_fact(call_operand)
                        elif (
                            call is not None
                            and call.owner == fn.binding_id
                            and call.kind == "direct_local"
                        ):
                            target = self.functions.get(call.target)
                            rf = (
                                target.results[0].type
                                if target is not None
                                and len(target.results) == 1
                                else None
                            )
                        else:
                            rf = None
                        if call is not None and rf is not None:
                            if rf.kind == "pointer":
                                # `*G()` requires a pointer to a
                                # container; `for range G()`
                                # auto-derefs pointer-to-array only —
                                # the same sugar rule `for range p`
                                # follows.
                                elem = rf.elem
                                if elem is not None and elem.kind in {
                                    "slice",
                                    "array",
                                    "map",
                                } and (not sugar or elem.kind == "array"):
                                    computed = (
                                        call_operand,
                                        elem,
                                        rf.type_id
                                        or (
                                            call_member.id
                                            if call_member is not None
                                            else call.target
                                        )
                                        + "/pointee",
                                    )
                            elif (
                                sugar
                                and rf.kind in {"slice", "array", "map"}
                            ):
                                computed = (
                                    call_operand,
                                    rf,
                                    (
                                        call_member.id
                                        if call_member is not None
                                        else call.target
                                    ),
                                )
                    if range_ident is not None:
                        bound = self._bound_container_pointee(
                            range_ident, locals_, params
                        )
                        if bound is None:
                            package_pointee = (
                                self._package_container_pointee(
                                    range_ident
                                )
                            )
                        # `for range p` auto-derefs only a
                        # pointer-to-array — the producer never
                        # emits the slice/map shape, and the gate
                        # keeps the admit honest anyway.
                        if sugar:
                            if bound is not None and bound[2].kind != "array":
                                bound = None
                            if (
                                package_pointee is not None
                                and package_pointee[1].kind != "array"
                            ):
                                package_pointee = None
                if (
                    member is not None
                    or container_var is not None
                    or bound is not None
                    or package_pointee is not None
                    or computed is not None
                ):
                    # Ranging a container in external state — an
                    # imported member (`lib.VA`, `lib.VM`), the
                    # unit's own package-level container var, or a
                    # container pointee (`*p`, `*GP`) — reads no
                    # binding's tracked value: index/key and element
                    # carry no parameter deps — like an index read —
                    # while the read still records the imported
                    # transfer and pins the container, key and
                    # element identities. A bound pointer's elements
                    # DO carry deps: the pointer's aim picks caller
                    # memory, so the element name gets deps(p) and
                    # every earlier indirect store like `(*p)[i]`.
                    # At most two names bind; the second (element)
                    # and a map's key must each hold a modelled type.
                    if len(lefts) > 2 or any(
                        l.type != "identifier" for l in lefts
                    ):
                        raise _Unsupported(
                            "unsupported_statement", _span(clause)
                        )
                    if (
                        bound is not None
                        or package_pointee is not None
                        or computed is not None
                    ):
                        fact = (
                            bound[2]
                            if bound is not None
                            else (
                                package_pointee[1]
                                if package_pointee is not None
                                else computed[1]
                            )
                        )
                        target = (
                            bound[1]
                            if bound is not None
                            else (
                                package_pointee[0]
                                if package_pointee is not None
                                else computed[2]
                            )
                        )
                        self._pin_fact_identities(fact)
                    else:
                        container = (
                            member
                            if member is not None
                            else container_var
                        )
                        fact = container.type
                        target = container.id
                        if member is not None:
                            self._pin_member_type(member)
                        else:
                            self._pin_fact_identities(fact)
                    key = fact.key
                    if key is not None and key.type_id:
                        self.pinned.add(key.type_id)
                    elem = fact.elem
                    if elem is not None and elem.type_id:
                        self.pinned.add(elem.type_id)
                    computed_args = ()
                    computed_call = None
                    if computed is not None:
                        # `for range *G()` — the callee's body is
                        # opaque to the summary (a container result
                        # is outside the scalar signature fragment
                        # anyway), so the call gets the
                        # opaque-callee model rather than
                        # `expression`'s: argument deps union, an
                        # imported transfer marks the external read,
                        # `effects` stays honest, and `&x` arguments
                        # fold like any effectful call's. Evaluate
                        # whether one name binds or two — the call
                        # runs either way — and pin the callee's
                        # signature types so redeclaring one flags
                        # this summary stale.
                        call_node, _, _ = computed
                        call = self.calls[self.node_key(call_node)]
                        arguments_node = call_node.child_by_field_name(
                            "arguments"
                        )
                        args = (
                            _children(arguments_node)
                            if arguments_node is not None
                            else []
                        )
                        if tuple(
                            self.node_key(arg) for arg in args
                        ) != tuple(_key3(a) for a in call.arguments):
                            raise _Unsupported(
                                "call_mapping_unavailable",
                                _span(call_node),
                                call.target,
                            )
                        computed_args = ()
                        target_fn = self.functions.get(call.target)
                        if call.method:
                            # `for range st.Items()` — the receiver
                            # operand evaluates first like the
                            # `st.M(args)` call path, so the elements
                            # inherit its deps and a pointer receiver
                            # folds the callee's writes back.
                            range_function_node = (
                                call_node.child_by_field_name(
                                    "function"
                                )
                            )
                            while (
                                range_function_node is not None
                                and range_function_node.type
                                == "parenthesized_expression"
                            ):
                                range_function_node = next(
                                    iter(
                                        range_function_node
                                        .named_children
                                    ),
                                    None,
                                )
                            range_receiver_node = (
                                range_function_node
                                .child_by_field_name("operand")
                                if (
                                    range_function_node is not None
                                    and range_function_node.type
                                    == "selector_expression"
                                )
                                else None
                            )
                            if range_receiver_node is None:
                                raise _Unsupported(
                                    "call_mapping_unavailable",
                                    _span(call_node),
                                    call.target,
                                )
                            range_receiver_deps = self.expression(
                                range_receiver_node, fn, params,
                                scope, transfers, count, 0,
                            )
                            if (
                                target_fn is not None
                                and target_fn.receiver is not None
                                and target_fn.receiver.type.kind
                                != "pointer"
                            ):
                                range_root = self._receiver_root_ref(
                                    range_receiver_node
                                )
                                range_root_binding = (
                                    self.bindings.get(
                                        range_root.binding_id
                                    )
                                    if range_root is not None
                                    else None
                                )
                                if (
                                    range_root_binding is not None
                                    and range_root_binding.type.kind
                                    == "pointer"
                                ):
                                    range_receiver_deps |= (
                                        self.indirect_writes
                                    )
                            computed_args = (range_receiver_deps,)
                        computed_args = computed_args + tuple(
                            self.expression(
                                arg, fn, params, scope,
                                transfers, count, 0,
                            )
                            for arg in args
                        )
                        computed_call = call
                        if call.method:
                            # A method's receiver reads like an
                            # argument: `Items` may hand `r`'s value
                            # to a callback `h`, so its deps join
                            # the fold the argument reads queued.
                            call_key = self.node_key(call_node)
                            self._call_arg_deps[call_key] = (
                                self._call_arg_deps.get(
                                    call_key, frozenset()
                                )
                                | range_receiver_deps
                            )
                        # `for range lib.G(h, x)` — a func-typed
                        # argument may run inside the opaque callee:
                        # drain the invocations the argument reads
                        # queued (the call node itself never passes
                        # through `expression` on this path).
                        self._fold_func_arg_invocations(
                            call_node, params, scope, transfers
                        )
                        if call_member is not None:
                            # An imported bodyless callee — its
                            # declared signature types pin like a
                            # member read's, the call counts opaque
                            # for --summary-aware-calls, and a chan
                            # argument promotes onto the shared queue
                            # like the index-read fold's.
                            self.pinned.update(
                                getattr(
                                    call_member,
                                    "signature_type_ids",
                                    (),
                                )
                                or ()
                            )
                            if call.kind == "external_or_bodyless":
                                self._opaque_spans.add(_key3(call.span))
                            self._promote_chan_call_args(
                                call_node, "", scope, params
                            )
                        if target_fn is not None:
                            for signature_param in (
                                *(
                                    (target_fn.receiver,)
                                    if target_fn.receiver is not None
                                    else ()
                                ),
                                *target_fn.parameters,
                                *target_fn.results,
                            ):
                                self._pin_fact_identities(
                                    signature_param.type
                                )
                        range_write_args = list(args)
                        if call.method:
                            range_write_args.append(range_receiver_node)
                        self._store_call_writes(
                            range_write_args,
                            frozenset().union(*computed_args)
                            if computed_args
                            else frozenset(),
                            scope,
                            params,
                        )
                        if (
                            target_fn is not None
                            and target_fn.receiver is not None
                            and target_fn.receiver.type.kind
                            == "pointer"
                        ):
                            range_receiver_operand = (
                                range_receiver_node
                                if call.method
                                else (args[0] if args else None)
                            )
                            range_rref = (
                                self._receiver_root_ref(
                                    range_receiver_operand
                                )
                                if range_receiver_operand is not None
                                else None
                            )
                            range_rbinding = (
                                self.bindings.get(
                                    range_rref.binding_id
                                )
                                if range_rref is not None
                                else None
                            )
                            if (
                                range_rref is not None
                                and range_rbinding is not None
                                and (
                                    range_rref.binding_id in scope
                                    or range_rref.binding_id in params
                                )
                            ):
                                range_stored = (
                                    frozenset().union(*computed_args)
                                    if computed_args
                                    else frozenset()
                                )
                                if (
                                    range_rbinding.type.kind
                                    == "pointer"
                                ):
                                    self.indirect_writes |= (
                                        range_stored
                                    )
                                else:
                                    range_base = (
                                        scope.get(
                                            range_rref.binding_id
                                        )
                                        if range_rref.binding_id
                                        in scope
                                        else frozenset(
                                            {
                                                params[
                                                    range_rref
                                                    .binding_id
                                                ]
                                            }
                                        )
                                    )
                                    scope[range_rref.binding_id] = (
                                        range_base | range_stored
                                    )
                    transfers.append(
                        CallTransfer(
                            FileSpan(
                                self.current_file,
                                right.start_byte,
                                right.end_byte,
                            ),
                            target,
                            computed_args,
                            frozenset(),
                            imported=True,
                        )
                    )
                    if computed_call is not None:
                        # `*G()` — the shared transfer above pins the
                        # result pointee's identity; the call itself
                        # pins the callee's. A direct container
                        # result (`G()`) names `call.target` in both,
                        # so the shared transfer already covers it.
                        # A bodyless imported callee records an empty
                        # `call.target` — the member's id stands in
                        # for it (an empty identity would mark every
                        # consumer summary stale).
                        second_target = computed_call.target or (
                            call_member.id
                            if call_member is not None
                            else ""
                        )
                        if second_target and computed[2] != second_target:
                            transfers.append(
                                CallTransfer(
                                    computed_call.span,
                                    second_target,
                                    computed_args,
                                    frozenset(),
                                    imported=True,
                                )
                            )
                    value_deps = frozenset()
                    if bound is not None:
                        if (
                            bound[2].kind == "array"
                            and len(lefts) <= 1
                        ):
                            # `for i := range p` and `for range
                            # *p` never evaluate the operand: Go
                            # skips the range expression when at
                            # most one iteration variable is
                            # present and `len(x)` is constant.
                            # The pointer write is not observed
                            # and no element binds at all (the
                            # index is dep-free), so nothing
                            # carries `p`'s deps.
                            pass
                        else:
                            # `for range *p` — each element (and a
                            # map's key, when only one name
                            # binds) is caller memory the
                            # pointer's aim selects, so the bound
                            # name carries the pointer's own deps
                            # and every earlier indirect store,
                            # the same union `(*p)[i]`'s read
                            # reports.
                            value_deps = self.expression(
                                range_ident, fn, params, scope,
                                transfers, count, 0,
                            ) | self.indirect_writes
                    elif computed is not None:
                        # `for range *G()` — the elements (and a
                        # map's key, when only one name binds) live
                        # in the memory the opaque result aims at,
                        # which may alias any escaped binding like
                        # a `*p` read: the argument deps (already
                        # evaluated above) union with every escaped
                        # binding's current deps and every indirect
                        # store.
                        value_deps = (
                            frozenset().union(*computed_args)
                            if computed_args
                            else frozenset()
                        )
                        for escaped_id in self.escaped:
                            if escaped_id in scope:
                                value_deps |= scope[escaped_id]
                            elif escaped_id in params:
                                value_deps |= {params[escaped_id]}
                        value_deps |= self.indirect_writes
                    # Each name's declared type comes from the
                    # compiler's binding — scalar-or-pointer, matching
                    # the index-read rule (a struct element or a
                    # string map key stays closed). A map's key is
                    # stored data like the element — a callee- or
                    # caller-produced container's key carries the
                    # same deps the element does; a slice index
                    # stays dep-free.
                    self._bind_range_names(
                        lefts, scope, params, conditional, value_deps,
                        (
                            value_deps
                            if fact is not None
                            and fact.kind == "map"
                            else frozenset()
                        ),
                    )
                    if (
                        (bound is not None or computed is not None)
                        and fact is not None
                        and (
                            bound is not None
                            or fact.kind != "array"
                        )
                        and len(lefts) >= 1
                        and len(lefts) <= 2
                    ):
                        # A map's key is stored data — keys added
                        # mid-iteration surface on later passes, so
                        # the key name re-joins like the element.
                        # An array VALUE ranges over a start-time
                        # copy: mid-iteration writes to the original
                        # never reach the iteration, so nothing
                        # re-joins. A bound POINTER ranges over the
                        # pointee's live elements — `for _, v :=
                        # range p` reads `(*p)[i]` fresh each pass,
                        # so even a `*[N]T` operand re-joins.
                        if (
                            fact.kind == "map"
                            and lefts[0].type == "identifier"
                            and lefts[0].text != b"_"
                        ):
                            key_binding = self.bindings_by_span.get(
                                self.node_key(lefts[0])
                            )
                            if key_binding is not None:
                                range_key = (
                                    key_binding.id,
                                    value_deps,
                                    None,
                                    computed is not None,
                                )
                            else:
                                key_ref = self.references.get(
                                    self.node_key(lefts[0])
                                )
                                if key_ref is not None:
                                    range_key = (
                                        key_ref.binding_id,
                                        value_deps,
                                        None,
                                        computed is not None,
                                    )
                        if len(lefts) == 2 and lefts[1].text != b"_":
                            elem_binding = self.bindings_by_span.get(
                                self.node_key(lefts[1])
                            )
                            if elem_binding is not None:
                                range_elem = (elem_binding.id, value_deps, None, False)
                            else:
                                elem_ref = self.references.get(
                                    self.node_key(lefts[1])
                                )
                                if elem_ref is not None:
                                    range_elem = (
                                        elem_ref.binding_id,
                                        value_deps,
                                        None,
                                        False,
                                    )
                else:
                    if right is None or len(lefts) > 1 or (
                        lefts and lefts[0].type != "identifier"
                    ):
                        raise _Unsupported(
                            "unsupported_statement", _span(clause)
                        )
                    chan = self._chan_binding(right, scope, params)
                    if chan is not None and (
                        chan.id in params
                        or chan.id in self.external_chan_locals
                    ):
                        # `for v := range ch` over a channel
                        # parameter iterates a queue the caller
                        # shares — each element reads external
                        # state like `<-ch`: the parameter's own
                        # index for provenance, every earlier send
                        # via `indirect_writes`, and an imported
                        # transfer keeps `effects` honest.
                        transfers.append(
                            CallTransfer(
                                FileSpan(
                                    self.current_file,
                                    right.start_byte,
                                    right.end_byte,
                                ),
                                chan.id,
                                (),
                                frozenset(),
                                imported=True,
                            )
                        )
                        rdeps = (
                            (
                                frozenset({params[chan.id]})
                                if chan.id in params
                                else scope.get(
                                    chan.id, frozenset()
                                )
                            )
                            | self.indirect_writes
                        )
                    else:
                        external = (
                            self._external_chan_operand(right, params)
                            if chan is None
                            else None
                        )
                        if external is not None:
                            # `for v := range GC` — elements come
                            # from external queue state: whatever
                            # earlier sends broadcast into
                            # `indirect_writes`, re-joined each
                            # fixed-point pass through the `None`
                            # arm like a `chan` parameter's.
                            target_id, fact = external
                            self._pin_fact_identities(fact)
                            transfers.append(
                                CallTransfer(
                                    FileSpan(
                                        self.current_file,
                                        right.start_byte,
                                        right.end_byte,
                                    ),
                                    target_id,
                                    (),
                                    frozenset(),
                                    imported=True,
                                )
                            )
                            rdeps = self.indirect_writes
                            chan = self.bindings.get(
                                target_id
                            ) or self.members.get(target_id)
                        elif (
                            field_chan := self._bound_field_chan(
                                right, scope, params
                            )
                        ) is not None:
                            # `for v := range p.C` — the caller-memory
                            # queue a bound pointer's field names:
                            # the pointer's deps join the read, the
                            # member's id records the mutation, and
                            # the element re-joins `indirect_writes`
                            # through the `None` arm.
                            pointees, member, root_ref = field_chan
                            self.pinned.update(
                                p.id
                                for p in pointees
                                if not p.id.endswith("/pointee")
                            )
                            self._pin_member_type(member)
                            self._pin_fact_identities(member.type)
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
                            rdeps = (
                                self.indirect_writes
                                | self._deref_read_deps(
                                    root_ref.binding_id, params, scope
                                )
                                | self._field_chan_deps(
                                    member.id, scope, params
                                )
                            )
                            chan = (
                                self.members.get(member.id)
                                or self.bindings.get(member.id)
                            )
                        elif (
                            chan is None
                            and (
                                chan_member := self._chan_result_call(
                                    right
                                )
                            )
                            is not None
                            and hasattr(chan_member, "result_types")
                        ):
                            # `for v := range lib.G()` — the callee-
                            # produced external queue an imported
                            # member's lone scalar-`chan` result
                            # names: elements re-join
                            # `indirect_writes` like a `chan`
                            # parameter's, and the read records on
                            # the member's identity with the result
                            # type's named identities pinned.
                            member = chan_member
                            self._pin_member_type(member)
                            for result_type in member.result_types:
                                self._pin_fact_identities(result_type)
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
                            # The call's own arguments still evaluate
                            # — `lib.G(x)` reads `x`, and the callee
                            # may send `x` on the queue it returns or
                            # write through a pointer/channel argument
                            # — so the deps join the read and the
                            # escaped fold an opaque call applies.
                            arg_node = right
                            while (
                                arg_node is not None
                                and arg_node.type
                                == "parenthesized_expression"
                            ):
                                arg_node = next(
                                    (
                                        c
                                        for c in arg_node.named_children
                                        if c.type != "comment"
                                    ),
                                    None,
                                )
                            range_args = (
                                arg_node.child_by_field_name("arguments")
                                if arg_node is not None
                                else None
                            )
                            arg_deps: frozenset[int] = frozenset()
                            if range_args is not None:
                                for arg in _children(range_args):
                                    arg_deps |= self.expression(
                                        arg, fn, params, scope,
                                        transfers, count, 0,
                                    )
                            self.indirect_writes |= arg_deps
                            for escaped_id in self.escaped:
                                self._store(
                                    scope, params, escaped_id,
                                    arg_deps, True,
                                )
                            rdeps = self.indirect_writes
                            chan = member
                        else:
                            rdeps = self.expression(
                                right, fn, params, scope, transfers,
                                count, 0,
                            )
                            iter_operand = right
                            while (
                                iter_operand is not None
                                and iter_operand.type
                                == "parenthesized_expression"
                            ):
                                iter_operand = next(
                                    (
                                        c
                                        for c in iter_operand.named_children
                                        if c.type != "comment"
                                    ),
                                    None,
                                )
                            func_iter = (
                                iter_operand is not None
                                and iter_operand.type
                                == "call_expression"
                                and self._func_iterator_result(
                                    iter_operand
                                )
                            )
                            if func_iter:
                                # `for v := range lib.Iter(&a)` —
                                # a func-typed result is invoked each
                                # iteration; the opaque callee reads
                                # (and its pointer arguments may
                                # write) caller memory, so like
                                # `for range *G()` the element joins
                                # every escaped binding's current
                                # deps and every indirect store.
                                for escaped_id in self.escaped:
                                    if escaped_id in scope:
                                        rdeps |= scope[escaped_id]
                                    elif escaped_id in params:
                                        rdeps |= {
                                            params[escaped_id]
                                        }
                                rdeps |= self.indirect_writes
                    if lefts and lefts[0].text != b"_":
                        binding = self.bindings_by_span.get(self.node_key(lefts[0]))
                        if binding is not None:
                            chan_elem = (
                                binding.type.kind == "chan"
                                and self._scalar_chan_binding(binding.id)
                                and chan is not None
                                and self._chan_chan_fact(chan.type)
                            )
                            if (
                                binding.type.kind
                                not in {"integer", "boolean", "pointer"}
                                and not chan_elem
                            ):
                                raise _Unsupported(
                                    "binding_unavailable", _span(lefts[0])
                                )
                            scope[binding.id] = rdeps
                            if chan_elem:
                                # `for c := range cc` — each element
                                # is a channel received out of the
                                # external `chan chan` queue, binding
                                # an external name like `c := <-cc`.
                                self.external_chan_locals.add(
                                    binding.id
                                )
                            if chan is not None:
                                # `for v := range ch` — the element
                                # name re-joins the queue's widened
                                # set each fixed-point pass, like the
                                # bound-container element does. A
                                # channel parameter's queue lives in
                                # `indirect_writes`, not `scope`, so
                                # it re-joins through the `None` arm.
                                range_elem = (
                                    binding.id,
                                    rdeps,
                                    (
                                        chan.id
                                        if chan.id in scope
                                        and chan.id
                                        not in self.external_chan_locals
                                        else None
                                    ),
                                    False,
                                )
                            elif func_iter:
                                # `for v := range lib.Iter(&a)` —
                                # the element re-joins escaped
                                # memory each pass like a chan's.
                                range_elem = (
                                    binding.id, rdeps, None, True
                                )
                        else:
                            ref = self.references.get(self.node_key(lefts[0]))
                            if ref is None or (
                                ref.binding_id not in scope
                                and ref.binding_id not in params
                            ):
                                raise _Unsupported(
                                    "binding_unavailable", _span(lefts[0])
                                )
                            ref_binding = self.bindings.get(
                                ref.binding_id
                            )
                            chan_elem = (
                                ref_binding is not None
                                and ref_binding.type.kind == "chan"
                                and self._scalar_chan_binding(
                                    ref.binding_id
                                )
                                and chan is not None
                                and self._chan_chan_fact(chan.type)
                            )
                            self._store(
                                scope, params, ref.binding_id, rdeps, conditional,
                            )
                            if chan_elem:
                                # `for c = range cc` over an existing
                                # scalar-`chan` name — same external
                                # element binding as the `:=` form;
                                # a stale `c := ch` alias must not
                                # keep `<-c` resolving to the old
                                # queue.
                                self.chan_aliases.pop(
                                    ref.binding_id, None
                                )
                                self.external_chan_locals.add(
                                    ref.binding_id
                                )
                            if chan is not None:
                                range_elem = (
                                    ref.binding_id,
                                    rdeps,
                                    (
                                        chan.id
                                        if chan.id in scope
                                        and chan.id
                                        not in self.external_chan_locals
                                        else None
                                    ),
                                    False,
                                )
                            elif func_iter:
                                range_elem = (
                                    ref.binding_id, rdeps, None, True
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
            # Resolution-table snapshots seen at pass boundaries. The
            # tables are rewritten, not unioned, so a store like
            # `f, g = g, f` (two closures capturing different locals)
            # can oscillate between snapshots forever while dep sets
            # stay put — a repeated snapshot breaks the cycle by
            # dropping the oscillating entries below.
            seen_resolutions: set = set()
            self.frames.append(frame)
            try:
                while True:
                    mark = len(transfers)
                    frame["exited"] = False
                    inner = dict(scope)
                    for range_rejoin in (range_elem, range_key):
                        if range_rejoin is None:
                            continue
                        # An element of `for range *p` is caller
                        # memory — a store through the pointer inside
                        # the body writes what the next iteration
                        # reads — so the bound name re-joins every
                        # pass's indirect writes until the point is
                        # fixed. `for range ch` re-joins the queue's
                        # own widened set instead: sends inside the
                        # body grow it in `inner`, and the pass join
                        # carries that growth back through `scope`.
                        # A map's key re-joins the same way: keys
                        # added mid-iteration surface on later passes.
                        elem_id, elem_base, elem_chan, elem_escaped = (
                            range_rejoin
                        )
                        extra = (
                            (
                                inner.get(elem_chan, frozenset())
                                | (
                                    self.indirect_writes
                                    if (
                                        elem_chan
                                        in self.external_chan_locals
                                        or elem_chan in params
                                    )
                                    else frozenset()
                                )
                            )
                            if elem_chan is not None
                            else self.indirect_writes
                        )
                        if elem_escaped:
                            # A func iterator's callee reads escaped
                            # caller memory each iteration — re-join
                            # every escaped binding's current deps.
                            for eid in self.escaped:
                                if eid in inner:
                                    extra |= inner[eid]
                                elif eid in params:
                                    extra |= {params[eid]}
                        # Each iteration REASSIGNS the element
                        # (and key) name — a value the body stored
                        # into it is clobbered next pass, so this
                        # replaces the slot rather than joining
                        # into it: `for _, v := range *p { …; v = x }`
                        # must not keep `x`'s deps on later passes.
                        inner[elem_id] = elem_base | extra
                    # A send to external state inside the body (a
                    # `chan` parameter, `*p`, `GC <- x`) grows
                    # `indirect_writes`, which no `inner` slot
                    # tracks — without comparing it the pass-join
                    # sees no change and stops before the element
                    # re-join above can observe the send.
                    iw_before = self.indirect_writes
                    # Alias/capture resolution tables sit outside
                    # `inner` too: a body pass that drops `h`'s
                    # function alias (or a literal's capture record)
                    # changes what `h(x)` resolves to without growing
                    # any dep set, so compare them like
                    # `indirect_writes`.
                    resolution_before = (
                        dict(self.func_aliases),
                        dict(self.closure_captures),
                        set(self.pointee_closures),
                        dict(self.chan_aliases),
                        set(self.external_chan_locals),
                        dict(self.closure_writes),
                        set(self.closure_star_writes),
                        set(self.closure_inner_calls),
                        set(self.opaque_callees),
                    )
                    resolution_changed = False
                    self._branch_sequence(
                        _children(body_node), fn, params, inner, transfers,
                        count, deps, saw_return, conditional,
                    )
                    if update is not None:
                        # The update runs after each pass so its writes
                        # seed the next iteration — an inc/dec is a
                        # dependency-preserving no-op, an assignment's
                        # RHS dependencies widen into the fixed point.
                        self._branch_statement(
                            update, fn, params, inner, transfers, count,
                            deps, saw_return, conditional,
                        )
                    resolution_after = (
                        dict(self.func_aliases),
                        dict(self.closure_captures),
                        set(self.pointee_closures),
                        dict(self.chan_aliases),
                        set(self.external_chan_locals),
                        dict(self.closure_writes),
                        set(self.closure_star_writes),
                        set(self.closure_inner_calls),
                        set(self.opaque_callees),
                    )
                    if resolution_after != resolution_before:
                        resolution_changed = True
                        snapshot = (
                            frozenset(resolution_after[0].items()),
                            frozenset(resolution_after[1].items()),
                            frozenset(resolution_after[2]),
                            frozenset(resolution_after[3].items()),
                            frozenset(resolution_after[4]),
                            frozenset(resolution_after[5].items()),
                            frozenset(resolution_after[6]),
                            frozenset(resolution_after[7]),
                            frozenset(resolution_after[8]),
                        )
                        if snapshot in seen_resolutions:
                            # An oscillating resolution (`f, g = g, f`
                            # swapping capture records) never converges
                            # — the entries alternate between states
                            # already seen. Break the cycle
                            # conservatively: function-alias targets are
                            # identities, not sets, so drop the moved
                            # aliases (the calls they fed resolve
                            # through the opaque external model), but
                            # UNION the moved capture records —
                            # deleting a capture list makes the call
                            # fall back to the name's literal-time dep
                            # set, which under-approximates a captured
                            # local re-seated inside the loop
                            # (`x = a` before `f()`). The union keeps
                            # every binding either state captured, so
                            # the call site resolves each one's
                            # CURRENT deps; convergence holds because
                            # the swap's `h = k` copy then writes the
                            # same union back. `pointee_closures`
                            # membership joins the same way — a name
                            # marked pointee-capturing in either state
                            # keeps the pointer-write model.
                            prev_a, prev_c, prev_p = resolution_before[:3]
                            cur_a, cur_c, cur_p = resolution_after[:3]
                            prev_w, prev_s, prev_i = resolution_before[5:8]
                            cur_w, cur_s, cur_i = resolution_after[5:8]
                            for key in cur_a.keys() | prev_a.keys():
                                if cur_a.get(key) != prev_a.get(key):
                                    self.func_aliases.pop(key, None)
                            for key in cur_c.keys() | prev_c.keys():
                                if cur_c.get(key) != prev_c.get(key):
                                    if key not in cur_c or key not in prev_c:
                                        # Absent in one alternating
                                        # state means the name also
                                        # binds a NON-literal callee
                                        # (`g := cb` for a param
                                        # callback): keep the unioned
                                        # record for the literal
                                        # alternative and mark the
                                        # name opaque so the call
                                        # still folds the external
                                        # callee's deps and effects.
                                        self.opaque_callees.add(key)
                                        self.closure_captures[key] = (
                                            cur_c.get(
                                                key, frozenset()
                                            )
                                            | prev_c.get(
                                                key, frozenset()
                                            )
                                        )
                                        self.closure_writes[key] = (
                                            cur_w.get(
                                                key, frozenset()
                                            )
                                            | prev_w.get(
                                                key, frozenset()
                                            )
                                        )
                                        if (
                                            key in cur_s
                                            or key in prev_s
                                        ):
                                            self.closure_star_writes.add(
                                                key
                                            )
                                        if (
                                            key in cur_i
                                            or key in prev_i
                                        ):
                                            self.closure_inner_calls.add(
                                                key
                                            )
                                    else:
                                        # Present in both states —
                                        # union keeps every binding
                                        # either literal captured, so
                                        # the call site resolves each
                                        # one's CURRENT deps and a
                                        # name-RHS copy writes the
                                        # same union back.
                                        self.closure_captures[key] = (
                                            cur_c[key] | prev_c[key]
                                        )
                                        self.closure_writes[key] = (
                                            cur_w.get(
                                                key, frozenset()
                                            )
                                            | prev_w.get(
                                                key, frozenset()
                                            )
                                        )
                                        if (
                                            key in cur_s
                                            or key in prev_s
                                        ):
                                            self.closure_star_writes.add(
                                                key
                                            )
                                        if (
                                            key in cur_i
                                            or key in prev_i
                                        ):
                                            self.closure_inner_calls.add(
                                                key
                                            )
                            for key in cur_p ^ prev_p:
                                self.pointee_closures.add(key)
                            prev_ca, prev_ce = (
                                resolution_before[3],
                                resolution_before[4],
                            )
                            cur_ca, cur_ce = (
                                resolution_after[3],
                                resolution_after[4],
                            )
                            for key in cur_ca.keys() | prev_ca.keys():
                                if cur_ca.get(key) != prev_ca.get(key):
                                    # An alternating channel alias
                                    # means the name may hold either
                                    # queue — detach to the external
                                    # union like a conditional
                                    # rebind does.
                                    self.chan_aliases.pop(key, None)
                                    self.external_chan_locals.add(
                                        key
                                    )
                            self.external_chan_locals |= (
                                cur_ce | prev_ce
                            )
                            # An alternating opaque mark resolves to
                            # opaque like every other resolution set —
                            # a name that MAY hold an unresolvable
                            # callee in either state keeps the
                            # external-capable model.
                            self.opaque_callees |= (
                                resolution_before[8]
                                | resolution_after[8]
                            )
                        else:
                            seen_resolutions.add(snapshot)
                    changed = (
                        self.indirect_writes != iw_before
                        or resolution_changed
                    )
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
                    # copies are stale. A pass that changed the
                    # resolution tables is different — its records can
                    # name a target no later pass reaches (an effectful
                    # alias resolved before a `h = pureLit` rebind), so
                    # dropping them would lose those effects.
                    if not resolution_changed:
                        del transfers[mark:]
                    passes += 1
                    # `indirect_writes` is a tracked slot outside
                    # `scope` — a body-only `GC <- x`/`p <- x` send
                    # grows it without touching any binding, so the
                    # bound counts one extra slot or a scope-empty
                    # function's bound is zero.
                    if passes > (len(scope) + 1) * (len(params) + 1):
                        raise _Unsupported("analysis_limit", _span(node))
            finally:
                self.frames.pop()
            # Loop-body reassignments join back by union: the loop may
            # execute zero or many times.
            self._join(locals_, scope, params)
            self._join_ptr(ptr_scope, params)
            return
        if kind == "expression_switch_statement":
            initializer = node.child_by_field_name("initializer")
            # `switch init; tag` runs a simple statement first — any name
            # it binds is scoped to the switch, like a for-clause init.
            scope = dict(locals_) if initializer is not None else locals_
            ptr_scope = dict(self._ptr_deps)
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
                        ptr_branch = dict(self._ptr_deps)
                        self._branch_sequence(
                            statements, fn, params, branch, transfers,
                            count, deps, saw_return, conditional,
                        )
                        if not falls:
                            self._join(scope, branch, params)
                            self._join_ptr(ptr_branch, params)
                            branch = None
                        continue
                    # Fall-through target — the body runs twice: once in
                    # the carried chain scope (the fallthrough path, with
                    # `exited` preserved across the chain), once as a
                    # fresh alternative (the direct-match path, which
                    # skips the preceding clause's writes).
                    self._branch_sequence(
                        statements, fn, params, branch, transfers,
                        count, deps, saw_return, conditional,
                    )
                    chain_exited = frame["exited"]
                    frame["exited"] = False
                    fresh = dict(scope)
                    ptr_fresh = dict(self._ptr_deps)
                    self._branch_sequence(
                        statements, fn, params, fresh, transfers,
                        count, deps, saw_return, conditional,
                    )
                    self._join(scope, fresh, params)
                    self._join_ptr(ptr_fresh, params)
                    if falls:
                        frame["exited"] = chain_exited
                    else:
                        self._join(scope, branch, params)
                        self._join_ptr(ptr_branch, params)
                        branch = None
            finally:
                self.frames.pop()
            if initializer is not None:
                self._join(locals_, scope, params)
                self._join_ptr(ptr_scope, params)
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
                    # x++ / x-- read the operand and change the
                    # value, never its dependencies.
                    if ref.binding_id in locals_:
                        self._record_read(locals_[ref.binding_id])
                    else:
                        self._record_read(
                            frozenset({params[ref.binding_id]})
                        )
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
            # `G++`/`G--` (and `G.V++`, `G[i]++`, `(*GP)++`) on a
            # package-level `var` mutate package state like
            # `lib.V++`: provenance-preserving, only the external
            # mutation records against the var's identity.
            package_write = self._package_var_write(operand)
            if package_write is not None:
                binding, extras, _ = package_write
                self._record_package_write(
                    operand, binding, extras,
                    fn, params, locals_, transfers, count,
                )
                return
            # `(*p)++` — an increment through a bound pointer mutates
            # the same untracked memory `*p = v` does, but is
            # provenance-preserving: an aliased binding keeps its own
            # deps across the store, so no fold is needed — only the
            # external mutation records.
            bound_ptr = self._bound_pointer_write(
                operand, locals_, params
            )
            if bound_ptr is not None:
                pointee_id, ref, _extra = bound_ptr
                # `(*p)++` reads the pointer and the old pointee —
                # the deref-read union covers `**pp`/`***t` too.
                self._record_read(
                    self._deref_read_deps(
                        ref.binding_id, params, locals_
                    )
                )
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
            # `(*p)[i]++` — an inc/dec through a bound container
            # pointee's element mutates caller memory like
            # `(*p)[i] = v` does, but is provenance-preserving like
            # `(*p)++`: the element's own value changes, no tracked
            # binding's deps do — only the external mutation records.
            bound_write = self._bound_container_write(
                operand, locals_, params
            )
            if bound_write is not None:
                pointee_id, extras, fact, ref = bound_write
                # `(*p)[i]++` reads the pointer and the old
                # element — `deps(p) ∪ indirect_writes` like the
                # read path.
                self._record_read(
                    self._pointer_deps(ref.binding_id, params, locals_)
                    | self.indirect_writes
                )
                self._pin_fact_identities(fact)
                for extra in reversed(extras):
                    if extra.type in _INDEX_LITERALS:
                        continue
                    self._record_read(
                        self.expression(
                            extra, fn, params, locals_,
                            transfers, count, 0,
                        )
                    )
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
            # `(*p)[i].F++` — the same increment on the element's
            # scalar field; the leaf field's identity records it.
            indexed_field = self._bound_pointee_index_field(
                operand, locals_, params
            )
            if indexed_field is not None:
                (
                    _root, _pid, fact, extras, field_member,
                    mid_members, ref,
                ) = indexed_field
                self._pin_fact_identities(fact)
                for mid_member in mid_members:
                    self._pin_fact_identities(mid_member.type)
                if field_member.type is not None:
                    self._pin_fact_identities(field_member.type)
                for extra in reversed(extras):
                    if extra.type in _INDEX_LITERALS:
                        continue
                    self._record_read(
                        self.expression(
                            extra, fn, params, locals_,
                            transfers, count, 0,
                        )
                    )
                self._record_read(
                    self._pointer_deps(ref.binding_id, params, locals_)
                    | self.indirect_writes
                )
                transfers.append(
                    CallTransfer(
                        FileSpan(
                            self.current_file,
                            operand.start_byte,
                            operand.end_byte,
                        ),
                        field_member.id,
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
                type_id, _ref, _nested = write_target
                # `st.F++` on a local composite is provenance-
                # preserving and local — no transfer records; the
                # field read still attributes st's conflated deps.
                if not type_id and _ref is not None:
                    base_deps = locals_.get(_ref.binding_id)
                    if base_deps is not None:
                        self._record_read(base_deps)
                if type_id:
                    if _ref is not None:
                        # `p.F++` on a bound pointer reads the
                        # pointer's provenance plus the field's
                        # recorded contents — never the folds in
                        # the pointer slot.
                        self._record_read(
                            self._pointer_deps(
                                _ref.binding_id, params, locals_
                            )
                            | self.indirect_writes
                        )
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
        if kind in {"go_statement", "defer_statement"}:
            # `go f(x)` / `defer f(x)` — Go evaluates the call's
            # function and arguments at the statement itself; only
            # the invocation is concurrent or deferred, so its
            # result is discarded while its effects fold here the
            # same may-happen way a regular call's do: a deferred
            # call runs before the function returns and a goroutine
            # races with it, so a later read cannot tell whether
            # the callee's writes landed — the union covers both.
            # The inner node must evaluate as a supported call on
            # its own; a literal callee is rejected upstream by the
            # extractor's `closure` kind.
            inner = _children(node)
            if len(inner) != 1:
                raise _Unsupported("unsupported_statement", _span(node))
            mark = len(transfers)
            ret = self.expression(
                inner[0], fn, params, locals_, transfers, count, 0
            )
            if kind == "defer_statement":
                # A deferred call runs at EVERY later `return` — after
                # the result expressions evaluate — so a callee that
                # can write may still change a named result:
                # `defer set(&r,x); return 0` returns x, not 0. What it
                # could write with is bounded by the call's arguments.
                # The call's own transfer is matched by span — argument
                # calls append theirs after it on the opaque paths.
                defer_arg_deps = frozenset()
                for t in transfers[mark:]:
                    if (
                        getattr(t.span, "start", None)
                            == inner[0].start_byte
                        and getattr(t.span, "end", None)
                            == inner[0].end_byte
                    ):
                        if t.arguments:
                            defer_arg_deps |= frozenset().union(
                                *t.arguments
                            )
                if not defer_arg_deps and isinstance(ret, frozenset):
                    # Opaque callees (func-value, interface dispatch)
                    # record `()` arguments but fold every evaluated
                    # dep — arguments included — into the call's
                    # result, so it bounds the writes conservatively.
                    arg_list = inner[0].child_by_field_name(
                        "arguments"
                    )
                    if arg_list is not None and _children(arg_list):
                        defer_arg_deps = ret
                if not defer_arg_deps:
                    return
                call = self.calls.get(self.node_key(inner[0]))
                callee = (
                    self.summarize(call.target)
                    if call is not None and call.target in self.functions
                    else None
                )
                if (
                    callee is None
                    or not callee.available
                    or callee.effects != "none_in_supported_fragment"
                ):
                    # May-write callee — its arguments bound what a
                    # deferred store can hand a named result.
                    self._defer_result_deps |= defer_arg_deps
            return
        if kind == "select_statement":
            # A select is a nondeterministic choice: each case's
            # communication op and body run in a fresh alternative
            # scope and every alternative joins back by union — like
            # an if/else chain whose guards are comm ops. `break`
            # inside a select body exits the select itself, matching
            # the switch frames. An empty `select {}` blocks forever —
            # it never reaches the following statements, so it stays
            # outside the fragment.
            clauses = [
                c
                for c in node.named_children
                if c.type in {"communication_case", "default_case"}
            ]
            if not clauses:
                raise _Unsupported("unsupported_statement", _span(node))
            frame = {"kind": "switch", "exited": False}
            self.frames.append(frame)
            try:
                # Go evaluates every case's channel operand and send
                # value once, in source order, on entering the
                # select — before a case is chosen. Run each comm
                # op against the entry scope so a later case's
                # operand calls (`case out <- h():` mutating a
                # captured pointer, say) reach every alternative's
                # join and every earlier case's reads; only the
                # receive's bound names and each clause's body run
                # inside a fresh alternative.
                receives: list[
                    tuple[list, Any, frozenset[int]] | None
                ] = []
                for clause in clauses:
                    receive = next(
                        (
                            s
                            for s in clause.named_children
                            if s.type == "receive_statement"
                        ),
                        None,
                    )
                    if receive is not None:
                        receives.append(
                            self._select_receive_eval(
                                receive, fn, params, locals_,
                                transfers, count,
                            )
                        )
                        continue
                    receives.append(None)
                    for sub in clause.named_children:
                        if sub.type == "send_statement":
                            self._branch_statement(
                                sub, fn, params, locals_, transfers,
                                count, deps, saw_return, conditional,
                            )
                # Every clause is an alternative starting from the
                # entry scope — joining one before evaluating the
                # next would leak the earlier case's stores into it
                # (`case i = <-ch:` must not change what `i` means
                # inside `default:`). Merge all branches into a
                # single environment and join it once.
                joined: dict[str, frozenset[int]] = {}
                joined_ptr: dict[str, frozenset[int]] = {}
                ptr_entry = dict(self._ptr_deps)
                chan_alias_entry = dict(self.chan_aliases)
                chan_external_entry = set(self.external_chan_locals)
                clause_aliases: list[dict] = []
                clause_externals: list[set] = []
                for clause, receive in zip(clauses, receives):
                    branch = dict(locals_)
                    # `_branch_sequence` rewrites the shared
                    # `_ptr_deps` map in place — swap in a fresh
                    # entry copy per clause or one alternative's
                    # pointer stores (`p = q`) leak into the next.
                    # The channel resolution maps mutate the same
                    # way — a rebind in `case A` must not detach
                    # `<-ch` inside `case B`.
                    self._ptr_deps = dict(ptr_entry)
                    self.chan_aliases = dict(chan_alias_entry)
                    self.external_chan_locals = set(chan_external_entry)
                    if receive is not None:
                        lefts, recv, recv_deps = receive
                        self._select_receive_store(
                            lefts, recv, recv_deps, clause, fn,
                            params, branch, transfers, count,
                            conditional,
                        )
                    body = next(
                        (
                            c
                            for c in clause.named_children
                            if c.type == "statement_list"
                        ),
                        None,
                    )
                    self._branch_sequence(
                        _children(body) if body is not None else [],
                        fn, params, branch, transfers,
                        count, deps, saw_return, conditional,
                    )
                    for bid, bdeps in branch.items():
                        joined[bid] = joined.get(
                            bid, frozenset()
                        ) | bdeps
                    for bid, bdeps in self._ptr_deps.items():
                        joined_ptr[bid] = joined_ptr.get(
                            bid, frozenset()
                        ) | bdeps
                    clause_aliases.append(dict(self.chan_aliases))
                    clause_externals.append(
                        set(self.external_chan_locals)
                    )
                # Post-join a channel name keeps its alias only where
                # every clause's map agrees; a disagreement means it
                # may hold either queue — the same "either queue"
                # union a conditional rebind resolves to external.
                self.external_chan_locals = set(chan_external_entry)
                for ext in clause_externals:
                    self.external_chan_locals |= ext
                detached_queues: dict[str, set] = {}
                self.chan_aliases = {}
                for bid in {
                    k for m in clause_aliases for k in m
                } | set(chan_alias_entry):
                    alias_values = {m.get(bid) for m in clause_aliases}
                    if len(alias_values) == 1:
                        only = alias_values.pop()
                        if only is not None:
                            self.chan_aliases[bid] = only
                    else:
                        self.external_chan_locals.add(bid)
                        detached_queues[bid] = {
                            v for v in alias_values if v is not None
                        }
                self._join(locals_, joined, params)
                # A maybe-detached name's slot also unions every
                # queue it could still mean — a case that kept the
                # old alias sees that queue's contents on a later
                # receive.
                for bid, tgts in detached_queues.items():
                    for tgt in tgts:
                        locals_[bid] = (
                            locals_.get(bid, frozenset())
                            | joined.get(tgt, frozenset())
                        )
                for bid, bdeps in joined_ptr.items():
                    base = ptr_entry.get(bid)
                    if base is None:
                        base = (
                            frozenset({params[bid]})
                            if bid in params
                            else frozenset()
                        )
                    ptr_entry[bid] = base | bdeps
                self._ptr_deps = ptr_entry
            finally:
                self.frames.pop()
            return
        if kind == "send_statement":
            # `ch <- x` on a local channel — the queue is one
            # conflated dep set: the sent value's deps accumulate
            # into `ch` (local state, no transfer — a send inside
            # the function is not an external effect). Sends
            # through a selector (`p.C <- x`), a param or a
            # package channel stay closed.
            channel = node.child_by_field_name("channel")
            value = node.child_by_field_name("value")
            if channel is None or value is None:
                raise _Unsupported("unsupported_statement", _span(node))
            binding = self._chan_binding(channel, locals_, params)
            if binding is None:
                # `GC <- x` / `lib.GC <- x` — a channel living in
                # external state (package-level or imported `var`).
                # The send mutates a queue outside the function's
                # locals: record it against the var/member's own
                # identity like a `chan` parameter send, and
                # broadcast the sent deps into `indirect_writes`.
                # `p.C <- x` — a channel field of a bound pointer's
                # pointee — mutates caller memory the same way,
                # recorded on the field member's identity.
                external = self._external_chan_operand(channel, params)
                field_chan = (
                    self._bound_field_chan(channel, locals_, params)
                    if external is None
                    else None
                )
                if external is None and field_chan is None:
                    raise _Unsupported(
                        "unsupported_statement", _span(node)
                    )
                if external is not None:
                    target_id, fact = external
                else:
                    pointees, member, root_ref = field_chan
                    target_id, fact = member.id, member.type
                    self.pinned.update(
                        p.id
                        for p in pointees
                        if not p.id.endswith("/pointee")
                    )
                    self._pin_member_type(member)
                value_deps = self.expression(
                    value, fn, params, locals_, transfers, count, 0
                )
                self._pin_fact_identities(fact)
                if external is not None:
                    # `cc <- ch` — sending a channel through an
                    # external queue hands `ch` to the caller's
                    # domain: every later op on it (`ch <- y`,
                    # `<-ch`, `close(ch)`) is an external effect.
                    # Promote the sent channel's queue root so the
                    # receive/sent sides stay connected through
                    # `indirect_writes`.
                    sent = self._chan_alias_target(
                        value, locals_, params
                    )
                    if sent is not None:
                        self.external_chan_locals.add(sent.id)
                    else:
                        # `cc <- G(q)` — a non-identifier send value
                        # may still hand one of its chan arguments'
                        # queues to the outer queue (`G` returning
                        # `q`), so the argument roots promote like
                        # an imported result's args.
                        self._promote_chan_call_args(
                            value, "", locals_, params
                        )
                if field_chan is not None:
                    # The send's destination read — like `(*p)[i]` —
                    # observes the pointer's deps and every earlier
                    # indirect store.
                    self._record_read(
                        self._pointer_deps(
                            root_ref.binding_id, params, locals_
                        )
                        | self.indirect_writes
                    )
                self.indirect_writes |= value_deps
                if field_chan is not None:
                    # The send writes into the pointee's contents:
                    # fold the value into the root binding like
                    # `p.F = v` does — a caller's deps on `p` then
                    # carry the queue, so `g(p)` sees this send —
                    # and into every queue the member may alias
                    # (`p.C = ch` sends reach `<-ch` too).
                    root_old = locals_.get(
                        root_ref.binding_id, frozenset()
                    )
                    if root_ref.binding_id in params:
                        root_old = root_old | frozenset(
                            {params[root_ref.binding_id]}
                        )
                    self._store(
                        locals_, params, root_ref.binding_id,
                        root_old | value_deps, conditional,
                    )
                    for token in self.field_chan_queues.get(
                        member.id, ()
                    ):
                        token_old = locals_.get(token, frozenset())
                        if token in params:
                            token_old = token_old | frozenset(
                                {params[token]}
                            )
                        self._store(
                            locals_, params, token,
                            token_old | value_deps, conditional,
                        )
                transfers.append(
                    CallTransfer(
                        FileSpan(
                            self.current_file,
                            node.start_byte,
                            node.end_byte,
                        ),
                        target_id,
                        (),
                        frozenset(),
                        imported=True,
                    )
                )
                return
            value_deps = self.expression(
                value, fn, params, locals_, transfers, count, 0
            )
            if binding.id in params or (
                binding.id in self.external_chan_locals
            ):
                # `ch <- x` on a channel parameter or a
                # callee-produced queue (`ch := g()`) — the queue is
                # shared beyond this function, so the send is an
                # external mutation: record it against the name's
                # real binding identity (staleness-honest, `effects`
                # unknown) and broadcast the sent deps into
                # `indirect_writes` — a later `<-ch` CAN observe
                # this exact value, so dropping them would
                # under-approximate.
                self.indirect_writes |= value_deps
                transfers.append(
                    CallTransfer(
                        FileSpan(
                            self.current_file,
                            node.start_byte,
                            node.end_byte,
                        ),
                        binding.id,
                        (),
                        frozenset(),
                        imported=True,
                    )
                )
            else:
                self._store(
                    locals_, params, binding.id,
                    locals_.get(binding.id, frozenset()) | value_deps,
                    conditional,
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
        if call is None or call.owner != fn.binding_id:
            return None
        if call.kind == "direct_import" and call.results == arity:
            return call
        if call.kind in {"direct_local", "method", "method_expr"}:
            # The probe only stamps a result arity on imported calls —
            # a local callee's own Function record declares it.
            target = self.functions.get(call.target)
            if (
                target is not None
                and len(target.results) == arity
                and arity > 1
            ):
                return call
        return None

    def _join(
        self,
        outer: dict[str, frozenset[int]],
        inner: dict[str, frozenset[int]],
        params: dict[str, int],
    ) -> None:
        """Union inner-scope reassignments back into the outer environment.

        Bindings created inside the inner scope never escape — only names
        that existed outside (lets or parameters) merge, and their
        dependencies union because the inner code path may not run. A
        dying binding's deps freeze into `_dead_local_deps`: a stored
        closure that captured it (`fs[0] = func() { return t }`) still
        reads the value it held at the merge.
        """
        for binding_id, deps in inner.items():
            if binding_id in outer:
                outer[binding_id] |= deps
            elif binding_id in params:
                # A reassigned parameter keeps its own dependency — the
                # branch may not run.
                outer[binding_id] = frozenset({params[binding_id]}) | deps
            else:
                self._dead_local_deps[binding_id] = (
                    self._dead_local_deps.get(
                        binding_id, frozenset()
                    )
                    | deps
                )

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
        result = self._expression(
            node, fn, params, locals_, transfers, count, depth
        )
        # Attribute the read to every statement frame still open — a
        # nested expression's deps are a subset of its parent's union,
        # so recursive calls appending their own returns change
        # nothing (the union is idempotent).
        if isinstance(result, frozenset):
            for frame in self._read_stack:
                frame.append(result)
        parent = node.parent if node is not None else None
        call_node = parent.parent if parent is not None else None
        arg_call = None
        if (
            parent is not None
            and parent.type == "argument_list"
            and call_node is not None
            and call_node.type == "call_expression"
        ):
            arg_call = call_node
        elif parent is not None and self._elem_call_conversion(parent):
            # `fs[i](g)` — the single-operand conversion form's
            # argument is a direct child of the conversion node.
            arg_call = parent
        elif (
            parent is not None
            and parent.type == "expression_list"
            and call_node is not None
            and self._elem_call_conversion(call_node)
        ):
            # `fs[i](g, x)` — a multi-argument conversion nests the
            # arguments under an `expression_list` operand.
            arg_call = call_node
        if isinstance(result, frozenset) and arg_call is not None:
            key = self.node_key(arg_call)
            self._call_arg_deps[key] = (
                self._call_arg_deps.get(key, frozenset()) | result
            )
        if node is not None and (
            node.type == "call_expression"
            or self._elem_call_conversion(node)
        ):
            key = self.node_key(node)
            if self._func_arg_invocations:
                self._fold_func_arg_invocations(
                    node, params, locals_, transfers
                )
            # The fold already popped this call's entry when a
            # callback was pending; for a plain call the accumulated
            # argument deps are dropped here instead of lingering
            # for the rest of the body.
            self._call_arg_deps.pop(key, None)
        return result

    def _queue_func_arg_invocation(
        self, node: Any, binding_id: str
    ) -> None:
        """Record `P(h, x)` — a func-typed local variable or parameter
        read inside a call's argument list — as a possible invocation
        the callee may run, so the call's own fold can apply the
        value's tracked writes and effects. Mirrors the declared-
        function branch of `_func_alias_bind` (`H(G, x)`)."""
        binding = self.bindings.get(binding_id)
        if (
            binding is None
            or binding.type is None
            or (
                binding.type.kind != "function"
                # A func-element collection argument admits too —
                # `g(fs)` may invoke `fs[k]` inside, so the
                # elements' write targets fold at the call site
                # like a passed func value's do.
                and not self._func_elem_collection(binding.type)
            )
        ):
            return
        # `P((h), x)` — parens sit between the identifier and the
        # argument list; walk through them like `_chan_call_args`.
        parent = node.parent
        while (
            parent is not None
            and parent.type == "parenthesized_expression"
        ):
            parent = parent.parent
        call_node = parent.parent if parent is not None else None
        call_target = None
        if (
            parent is not None
            and parent.type == "argument_list"
            and call_node is not None
            and call_node.type == "call_expression"
        ):
            call_target = call_node
        elif parent is not None and self._elem_call_conversion(parent):
            call_target = parent
        elif (
            parent is not None
            and parent.type == "expression_list"
            and call_node is not None
            and self._elem_call_conversion(call_node)
        ):
            call_target = call_node
        if call_target is not None:
            self._func_arg_invocations.setdefault(
                self.node_key(call_target), []
            ).append((node, binding_id))

    def _fold_func_arg_invocations(
        self,
        node: Any,
        params: dict[str, int],
        locals_: dict[str, frozenset[int]],
        transfers: list[CallTransfer],
    ) -> None:
        """Fold `H(G, x)`-shaped argument reads once the call's deps
        are known.

        A function value handed to a call may be invoked by the
        callee — `H(g, x)` calling `g(x)` — so each argument-position
        function name records a possible invocation as a transfer on
        its own identity: `imported` exactly like a resolved callee's
        transfer (an unbounded or unresolvable callee marks effects
        unknown). When G's own effects are unbounded or touch an
        external channel, the values it writes or sends are bounded
        only by the call's arguments, so the call's deps broadcast
        into `indirect_writes` for a later `<-q` to observe."""
        pending = self._func_arg_invocations.pop(
            self.node_key(node), ()
        )
        # What the callee may invoke the passed functions WITH: every
        # argument the call evaluated, not the call's result — a
        # `g(x); return 0` callee still hands `x` to the invoked
        # function even though its own result depends on nothing.
        arg_deps = self._call_arg_deps.pop(
            self.node_key(node), frozenset()
        )
        for arg_node, binding_id in pending:
            callee = (
                self.summarize(binding_id)
                if binding_id in self.functions
                else None
            )
            if binding_id in self.functions:
                unbounded = (
                    callee is None
                    or not callee.available
                    or callee.effects == "unknown"
                )
                external_chan = callee is not None and any(
                    self._external_chan_id(c.target)
                    for c in callee.calls
                )
            else:
                # `h := Id` — a local alias of a declared function
                # resolves exactly like the function-name argument
                # form (`H(G, x)`): a bounded pure callee keeps its
                # own effects instead of the opaque broadcast.
                alias = self.func_aliases.get(binding_id)
                if alias is not None and alias in self.functions:
                    aliased = self.summarize(alias)
                    unbounded = (
                        aliased is None
                        or not aliased.available
                        or aliased.effects == "unknown"
                    )
                    external_chan = aliased is not None and any(
                        self._external_chan_id(c.target)
                        for c in aliased.calls
                    )
                else:
                    # A local func value or parameter: a param binding,
                    # an opaque mark, or the absence of any resolvable
                    # literal record leaves the invoked value unknown;
                    # a tracked literal stays bounded unless it writes,
                    # dereferences, calls out, or captures external
                    # state.
                    has_literal = (
                        binding_id in self.closure_captures
                        or binding_id in self.closure_writes
                        or binding_id in self.pointee_closures
                        or binding_id in self.closure_star_writes
                        or binding_id in self.closure_inner_calls
                    )
                    effectful = (
                        bool(self.closure_writes.get(binding_id))
                        or binding_id in self.closure_star_writes
                        or binding_id in self.closure_inner_calls
                        or binding_id in self.pointee_closures
                        or any(
                            (
                                self._chan_root(cbid) in params
                                or self._chan_root(cbid)
                                in self.external_chan_locals
                            )
                            and self._scalar_chan_binding(cbid)
                            for cbid in self.closure_captures.get(
                                binding_id, ()
                            )
                        )
                    )
                    unbounded = (
                        binding_id in params
                        or binding_id in self.opaque_callees
                        or not has_literal
                        or effectful
                    )
                    external_chan = unbounded
            transfers.append(
                CallTransfer(
                    FileSpan(
                        self.current_file,
                        arg_node.start_byte,
                        arg_node.end_byte,
                    ),
                    binding_id,
                    (),
                    frozenset(),
                    imported=unbounded,
                )
            )
            if unbounded or external_chan:
                self.indirect_writes |= arg_deps
            # A passed LOCAL func value keeps its literal records —
            # `Pass(h, x)` where `h` may still be the literal that
            # writes `a = v`. If the callee invokes it, those named
            # write targets land like they do at a direct `h()` call;
            # the generic `indirect_writes` broadcast alone misses
            # them because a captured target need not be an escaped
            # binding.
            for target in self.closure_writes.get(
                binding_id, frozenset()
            ):
                self._store(locals_, params, target, arg_deps, True)
                self.func_aliases.pop(target, None)
                self.opaque_callees.add(target)
            if (
                unbounded
                or binding_id in self.closure_star_writes
                or binding_id in self.closure_inner_calls
            ):
                self.indirect_writes |= arg_deps
                for escaped_id in self.escaped:
                    self._store(
                        locals_, params, escaped_id, arg_deps, True
                    )

    def _record_read(self, deps: frozenset[int]) -> None:
        """Attribute an implicit read to every open statement
        frame. `x++`'s operand, `x op= e`'s LHS, a bare `return`'s
        named result and `st.F++`'s conflated base all read a
        binding's deps without routing through `expression()`, so
        the wrapper never sees them."""
        for frame in self._read_stack:
            frame.append(deps)

    def _pointer_deps(
        self,
        binding_id: str,
        params: dict[str, int],
        locals_: dict[str, frozenset[int]],
    ) -> frozenset[int]:
        """What the pointer binding itself depends on — its declared
        provenance — without the pointee contents broadcast stores
        folded into `locals_`. Every binding that reaches `locals_`
        does so through a declaration or a plain store, which records
        here first, so the lazy fallback below only ever sees an
        untouched slot. A parameter's pointer provenance is always
        its own dep — recorded entries supersede it once the name
        rebinds."""
        deps = self._ptr_deps.get(binding_id)
        if deps is None:
            if binding_id in params:
                return frozenset({params[binding_id]})
            deps = locals_.get(binding_id, frozenset())
            self._ptr_deps[binding_id] = deps
        return deps

    def _receiver_root_ref(self, operand_node: Any) -> Any:
        """The root identifier reference of a receiver operand.

        `st.M()` gives `st`; a field receiver `s.A.M()` walks the
        selector chain to `s`; `(*p).M()` unwraps the paren and the
        `*` to `p`. A computed operand (`g().M`) names no binding —
        returns None.
        """
        cur = operand_node
        while True:
            while (
                cur is not None
                and cur.type == "parenthesized_expression"
            ):
                cur = next(
                    (
                        c
                        for c in cur.named_children
                        if c.type != "comment"
                    ),
                    None,
                )
            if (
                cur is not None
                and cur.type == "unary_expression"
                and cur.children
                and cur.children[0].type == "*"
            ):
                cur = next(
                    (
                        c
                        for c in cur.named_children
                        if c.type != "comment"
                    ),
                    None,
                )
                continue
            if cur is not None and cur.type == "selector_expression":
                cur = cur.child_by_field_name("operand")
                continue
            break
        if cur is None or cur.type != "identifier":
            return None
        return self.references.get(self.node_key(cur))

    def _type_slot_ref_deps(
        self,
        node: Any,
        locals_: dict[str, frozenset[int]],
        params: dict[str, int],
    ) -> tuple[Any, frozenset[int]] | None:
        """The (reference, deps) pair of a bare name the grammar put
        in a type position — a `type_identifier` inside `generic_type`
        or `type_arguments`. `fs[i](x)` parses `fs` and `i` this way;
        both resolve through `locals_`/`params` like an `identifier`
        read. Anything else (a qualified or compound type node, an
        unresolvable name) returns None and keeps the callee closed.
        """
        if node is None or node.type != "type_identifier":
            return None
        ref = self.references.get(self.node_key(node))
        if ref is None or not ref.binding_id:
            return None
        binding_id = ref.binding_id
        if binding_id in locals_:
            return ref, locals_[binding_id]
        if binding_id in params:
            return ref, frozenset({params[binding_id]})
        binding = self.bindings.get(binding_id)
        if binding is not None and _scalar_constant(binding):
            return ref, frozenset()
        return None

    def _deref_read_deps(
        self,
        binding_id: str,
        params: dict[str, int],
        locals_: dict[str, frozenset[int]],
    ) -> frozenset[int]:
        """What dereferencing `binding_id` reads — the slot's own
        deps (folded pointee contents included), every escaped
        binding an `&x` may have aimed the pointer at, and every
        earlier indirect store — the union the `*p` read path
        builds."""
        deps = locals_.get(binding_id)
        if deps is None:
            deps = (
                frozenset({params[binding_id]})
                if binding_id in params
                else frozenset()
            )
        deps = deps | self.indirect_writes
        for escaped_id in self.escaped:
            if escaped_id in locals_:
                deps |= locals_[escaped_id]
            elif escaped_id in params:
                deps |= frozenset({params[escaped_id]})
        return deps

    def _join_ptr(
        self,
        before: dict[str, frozenset[int]],
        params: dict[str, int],
    ) -> None:
        """Mirror `_join` for `_ptr_deps`: stores inside a branch or
        loop body replaced the shared map unconditionally, so the
        pre-scope snapshot unions back as a may-write."""
        for binding_id in self._ptr_deps:
            if binding_id in before:
                self._ptr_deps[binding_id] |= before[binding_id]
            elif binding_id in params:
                self._ptr_deps[binding_id] |= frozenset(
                    {params[binding_id]}
                )

    def _expression(
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
        if kind == "nil":
            ref = self.references.get(self.node_key(node))
            if ref is not None and ref.binding_id:
                # `nil` is a redefinable identifier — a shadowed
                # nil resolves through `locals_`/`params` like
                # any other name.
                kind = "identifier"
            else:
                # `nil` carries no deps like a literal — a nil
                # read on a non-nilable type cannot compile anyway.
                return frozenset()
        if kind in {"identifier", "true", "false", "iota"}:
            ref = self.references.get(self.node_key(node))
            # Reassigned names (including parameters) resolve through
            # `locals_` first — their latest dependencies live there.
            if ref is not None and ref.binding_id in locals_:
                chan_root = (
                    self._chan_root(ref.binding_id)
                    if self._is_chan_binding(ref.binding_id)
                    else ref.binding_id
                )
                if chan_root != ref.binding_id:
                    # `ch2 := ch` names one queue under two names —
                    # a bare `G(ch2)` read surfaces what the queue
                    # may hold, so it reads the SOURCE binding's
                    # slot (plus a shared queue's send broadcast),
                    # not the snapshot `locals_[ch2]` froze at the
                    # copy.
                    if chan_root in locals_:
                        deps = locals_[chan_root]
                        if chan_root in self.external_chan_locals:
                            deps |= self.indirect_writes
                        return deps
                    if chan_root in params:
                        return (
                            frozenset({params[chan_root]})
                            | self.indirect_writes
                        )
                    return frozenset()
                deps = locals_[ref.binding_id]
                if ref.binding_id in self.external_chan_locals:
                    # `ch := g()` names a callee-produced queue —
                    # contents live in `indirect_writes`, like a
                    # channel parameter's.
                    deps |= self.indirect_writes
                self._queue_func_arg_invocation(node, ref.binding_id)
                return deps
            if ref is not None and ref.binding_id in params:
                chan_root = (
                    self._chan_root(ref.binding_id)
                    if self._is_chan_binding(ref.binding_id)
                    else ref.binding_id
                )
                if chan_root != ref.binding_id:
                    # `p = q` reseated the parameter's name onto
                    # another queue — the read surfaces that queue's
                    # contents, not p's own provenance slot.
                    if chan_root in locals_:
                        deps = locals_[chan_root]
                        if chan_root in self.external_chan_locals:
                            deps |= self.indirect_writes
                        return deps
                    if chan_root in params:
                        return (
                            frozenset({params[chan_root]})
                            | self.indirect_writes
                        )
                    return frozenset()
                deps = frozenset({params[ref.binding_id]})
                binding = self.bindings.get(ref.binding_id)
                if (
                    binding is not None
                    and binding.type is not None
                    and binding.type.kind == "function"
                ):
                    self._queue_func_arg_invocation(node, ref.binding_id)
                if (
                    binding is not None
                    and binding.type is not None
                    and binding.type.kind == "chan"
                ):
                    # Naming a channel parameter surfaces what the
                    # shared queue may hold — `G(ch)` after `ch <- x`
                    # must carry x's deps into the call, like `<-ch`
                    # does — so the bare read unions every earlier
                    # send's broadcast exactly like the receive.
                    deps |= self.indirect_writes
                return deps
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
                if binding.kind == "function":
                    # A declared function name reads as a value in a
                    # store's RHS position (`h := G`, `h = G`,
                    # `var h = G`) — the store records the alias and
                    # `h()` resolves through G's summary — or in a
                    # call's argument list (`H(G, x)`), which queues
                    # the possible invocation for the call's own
                    # fold. Any other use (return, operand) stays
                    # closed.
                    return self._func_alias_bind(node)
                if (
                    binding.kind == "variable"
                    and self._package_level(binding)
                    and binding.type is not None
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
                # `s.M` / `St.M` — a bound method value: the
                # selector field resolves to a same-package method,
                # not a field. The receiver operand evaluates like
                # the `st.M()` call operand; the binding site
                # records the (method, receiver) pair under the new
                # name so a later `f(args)` resolves through the
                # method's summary — `St.M` (a type-name operand)
                # records (method, None) and `f(recv, args)` puts
                # the receiver at argument 0. `g().M` (a computed
                # receiver) records nothing — a call through it
                # keeps the `indirect_or_selector` record closed.
                mv_parts = self._method_value_parts(node)
                if mv_parts is not None:
                    operand = node.child_by_field_name("operand")
                    if operand is None:
                        raise _Unsupported(
                            "non_parameter_reference", _span(node)
                        )
                    if mv_parts[1] is None:
                        # `St.M` — the operand names a TYPE, not a
                        # value: nothing evaluates. The binding site
                        # still records the (method, None) pair.
                        return frozenset()
                    return self.expression(
                        operand, fn, params, locals_,
                        transfers, count, depth + 1,
                    )
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
                field_index_nodes: set[Any] = set()
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
                        if idx.type in _INDEX_LITERALS:
                            continue
                        field_index_nodes.add(self.node_key(idx))
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
                    pointees, field_member, root_ref = bound
                    self.pinned.update(
                        p.id
                        for p in pointees
                        if not p.id.endswith("/pointee")
                    )
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
                    # The field's value may carry whatever earlier
                    # stores aimed at this memory: the root pointer's
                    # own deps (a `t.F = v` write accumulates into it)
                    # and every indirect store — an escaped binding
                    # can never be this pointee (`&st` stays closed),
                    # so unlike a bare `*p` scalar deref no escaped
                    # union applies.
                    deps = (
                        locals_.get(root_ref.binding_id)
                        if root_ref.binding_id in locals_
                        else (
                            frozenset({params[root_ref.binding_id]})
                            if root_ref.binding_id in params
                            else frozenset()
                        )
                    )
                    return deps | self.indirect_writes
                # `g(a).V` — a field of a call result: the call's
                # conflated result dep set covers whichever field the
                # read selects, so the operand evaluates like a
                # value. A method name (`g(a).M`) is filtered below —
                # `_method_value_parts` rejects computed operands, so
                # a method value on a call result stays closed.
                sel_operand = node.child_by_field_name("operand")
                while (
                    sel_operand is not None
                    and sel_operand.type == "parenthesized_expression"
                ):
                    sel_operand = next(
                        (
                            c
                            for c in sel_operand.named_children
                            if c.type != "comment"
                        ),
                        None,
                    )
                # `g(a).A.B` — walk the selector chain to its base:
                # only a call base means the field rides a call
                # result; an identifier base still takes the local
                # composite path (which keeps promoted-field reads
                # closed).
                sel_base = sel_operand
                while (
                    sel_base is not None
                    and sel_base.type == "selector_expression"
                ):
                    sel_base = sel_base.child_by_field_name("operand")
                    while (
                        sel_base is not None
                        and sel_base.type == "parenthesized_expression"
                    ):
                        sel_base = next(
                            (
                                c
                                for c in sel_base.named_children
                                if c.type != "comment"
                            ),
                            None,
                        )
                if (
                    sel_base is not None
                    and sel_base.type == "call_expression"
                ):
                    # Every selector level must resolve to a declared
                    # field — `g().M` names a method value, not a
                    # field read, and stays closed like `s.M` on a
                    # computed operand does.
                    fields_ok = True
                    field_idents = []
                    cur_sel = node
                    while (
                        cur_sel is not None
                        and cur_sel.type == "selector_expression"
                    ):
                        fld = cur_sel.child_by_field_name("field")
                        fld_ref = (
                            self.references.get(self.node_key(fld))
                            if fld is not None
                            else None
                        )
                        fld_ident = self._field_identity(fld_ref)
                        if fld_ident is None:
                            fields_ok = False
                            break
                        field_idents.append(fld_ident)
                        cur_sel = cur_sel.child_by_field_name(
                            "operand"
                        )
                        while (
                            cur_sel is not None
                            and cur_sel.type
                            == "parenthesized_expression"
                        ):
                            cur_sel = next(
                                (
                                    c
                                    for c in cur_sel.named_children
                                    if c.type != "comment"
                                ),
                                None,
                            )
                    if fields_ok:
                        deps = self.expression(
                            sel_operand, fn, params, locals_,
                            transfers, count, depth + 1,
                        )
                        # Pin every level's declared field type —
                        # `g(s).A.B` reads through field `A` whose
                        # type `Q` may live in another file, so a
                        # `Q` redeclaration must flag this summary
                        # via `stale_dependents`.
                        for ident in field_idents:
                            ident_type = getattr(ident, "type", None)
                            if (
                                ident_type is not None
                                and ident_type.type_id
                            ):
                                self.pinned.add(ident_type.type_id)
                        # A pointer CROSSED by the read — a `*S`
                        # call result or an intermediate `*Q` field —
                        # means the read dereferences memory aliases
                        # may have written, so it reads like `*p`:
                        # escaped bindings' current deps and indirect
                        # writes union in, and the read is recorded
                        # as an external effect. A TERMINAL pointer
                        # field (`g().P` with `P *Q`) reads only the
                        # pointer value — no deref, no union.
                        result_type = self._call_result_type(sel_base)
                        ptr_type = (
                            result_type
                            if result_type is not None
                            and result_type.kind == "pointer"
                            else None
                        )
                        if ptr_type is None:
                            # `g(q).P` where `P` promotes through an
                            # embedded `*Q` — the syntactic chain
                            # names no pointer, but the read crosses
                            # one into caller memory. The terminal
                            # field's container is its own parent
                            # level's type, or the call result's.
                            container = (
                                getattr(
                                    field_idents[1], "type", None
                                )
                                if len(field_idents) > 1
                                else result_type
                            )
                            call = self.calls.get(
                                self.node_key(sel_base)
                            )
                            ptr_type = (
                                self._promoted_field_pointer(
                                    container, field_idents[0], call
                                )
                            )
                        if ptr_type is None:
                            # `field_idents[0]` is the terminal field
                            # read — `g().P` with `P *Q` yields the
                            # pointer VALUE without dereferencing.
                            # Only a pointer an earlier level crosses
                            # (`g().P.V`) dereferences.
                            for ident in field_idents[1:]:
                                ident_type = getattr(
                                    ident, "type", None
                                )
                                if (
                                    ident_type is not None
                                    and ident_type.kind == "pointer"
                                ):
                                    ptr_type = ident_type
                                    break
                        if ptr_type is not None:
                            deps |= self.indirect_writes
                            for escaped_id in self.escaped:
                                if escaped_id in locals_:
                                    deps |= locals_[escaped_id]
                                elif escaped_id in params:
                                    deps |= {params[escaped_id]}
                            transfers.append(
                                CallTransfer(
                                    FileSpan(
                                        self.current_file,
                                        node.start_byte,
                                        node.end_byte,
                                    ),
                                    ptr_type.type_id
                                    or getattr(
                                        field_idents[-1], "id", ""
                                    ),
                                    (),
                                    frozenset(),
                                    imported=True,
                                )
                            )
                        return deps
                # `st.V` / `st.A.B` — a field of a tracked local
                # composite: the binding's dep set conflates every
                # field, so the read returns it whole. Local state —
                # no transfer records, nothing pins.
                local = self._local_composite_base(node, locals_)
                if local is not None:
                    ref, resolved_fields = local
                    if not self._direct_field_chain(
                        ref, resolved_fields
                    ):
                        # `st.V` where `V` promotes through embedded
                        # `*Q` reads caller memory the conflated set
                        # cannot represent — a dep-free answer here
                        # would also report `effects` dishonestly, so
                        # promoted reads stay closed like promoted
                        # writes.
                        raise _Unsupported(
                            "non_parameter_reference", _span(node)
                        )
                    return locals_.get(ref.binding_id, frozenset())
                # `G.V` / `G.A.N` — a field of a package-level
                # composite (or pointer) var: package state is
                # external exactly like `lib.VS.F`, so the read is
                # dep-free while the leaf field's own identity
                # records it — both the root var and the leaf's
                # declared type pin for `stale_dependents`.
                package_field = self._package_composite_field_read(node)
                if package_field is not None:
                    gvar, field_ident, extras = package_field
                    self.pinned.add(gvar.id)
                    self._pin_fact_identities(gvar.type)
                    if field_ident.type is not None:
                        self._pin_fact_identities(field_ident.type)
                    transfers.append(
                        CallTransfer(
                            FileSpan(
                                self.current_file,
                                node.start_byte,
                                node.end_byte,
                            ),
                            field_ident.id,
                            (),
                            frozenset(),
                            imported=True,
                        )
                    )
                    # The index selects which slot the field comes
                    # from — `(*GA[i]).V` depends on `i` exactly like
                    # `GA[i]` does. Indexes the `lib.VSM[k].F`
                    # pre-scan already evaluated contribute their
                    # deps via `field_index_deps`; the rest (inside
                    # a deref operand) evaluate here, once.
                    deps = field_index_deps
                    for extra in reversed(extras):
                        if (
                            extra.type in _INDEX_LITERALS
                            or self.node_key(extra) in field_index_nodes
                        ):
                            continue
                        deps |= self.expression(
                            extra, fn, params, locals_,
                            transfers, count, 0,
                        )
                    return deps
                # `(*p)[i].F` — a field of the element a bound
                # container pointee's index selects: caller memory
                # like `(*p)[i]` itself, so the deps union the
                # pointer's own, the indexes' (the pre-scan's via
                # `field_index_deps`), and every indirect store —
                # the bound pointer cannot alias a tracked
                # composite (`&st` stays closed), so no escaped
                # union applies.
                indexed = self._bound_pointee_index_field(
                    node, locals_, params
                )
                if indexed is not None:
                    (
                        ident, pointee_id, fact, extras, field_member,
                        mid_members, _ref,
                    ) = indexed
                    self._pin_fact_identities(fact)
                    for mid_member in mid_members:
                        self._pin_fact_identities(mid_member.type)
                    if field_member.type is not None:
                        self._pin_fact_identities(field_member.type)
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
                    # Evaluate the indexes before snapshotting
                    # `indirect_writes`: a two-level operand escapes
                    # the pre-scan, and an index call can add
                    # indirect stores the leaf read must observe.
                    deps = field_index_deps
                    for extra in reversed(extras):
                        if (
                            extra.type in _INDEX_LITERALS
                            or self.node_key(extra) in field_index_nodes
                        ):
                            continue
                        deps |= self.expression(
                            extra, fn, params, locals_,
                            transfers, count, 0,
                        )
                    deps |= self.indirect_writes
                    deps |= self.expression(
                        ident, fn, params, locals_,
                        transfers, count, depth + 1,
                    )
                    return deps
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
        if kind == "func_literal":
            return self._func_literal(node, params, locals_)
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
            key_deps: frozenset[int] = frozenset()
            if key_node is not None:
                key_ref = (
                    self.references.get(self.node_key(key_node))
                    if key_node.type == "identifier"
                    else None
                )
                if self._field_identity(key_ref) is None:
                    # `M[K(x): v]` runs K before V — evaluate the key
                    # first so a side effect inside it is observed
                    # by the value's evaluation order.
                    key_deps = self.expression(
                        key_node, fn, params, locals_, transfers, count,
                        depth + 1,
                    )
            deps = self.expression(
                value_node, fn, params, locals_, transfers, count,
                depth + 1,
            )
            return deps | key_deps
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
                if (
                    kind == "unary_expression"
                    and operator is not None
                    and operator.type == "<-"
                ):
                    # `<-ch` on a local channel — the queue's whole
                    # conflated set (FIFO order is unmodelled; the
                    # union of every send is the sound
                    # over-approximation). A receive through a
                    # selector, a param or a package channel stays
                    # closed.
                    operand = node.child_by_field_name("operand")
                    binding = self._chan_binding(
                        operand, locals_, params
                    )
                    if binding is None:
                        # `<-GC` / `<-lib.GC` — receiving a queue in
                        # external state: whatever earlier sends put
                        # in is in `indirect_writes`; the rest is
                        # external content, dep-free like an imported
                        # read. The transfer records on the
                        # var/member's identity. `<-p.C` reads the
                        # caller-memory queue a bound pointer's field
                        # names — the pointer's own deps join like a
                        # `(*p)[i]` read's.
                        external = self._external_chan_operand(operand, params)
                        field_chan = (
                            self._bound_field_chan(
                                operand, locals_, params
                            )
                            if external is None
                            else None
                        )
                        if external is None and field_chan is None:
                            raise _Unsupported(
                                "non_parameter_reference", _span(node)
                            )
                        if external is not None:
                            target_id, fact = external
                            if self._chan_chan_fact(fact):
                                # `<-cc` pulls a channel out of the
                                # outer queue — the received name
                                # carries the queue's own deps
                                # (`cc := G(x)` hands `x` to
                                # `c := <-cc`; a bare param slot has
                                # no entry and stays dep-free).
                                base_deps = locals_.get(
                                    target_id, frozenset()
                                )
                            else:
                                base_deps = frozenset()
                        else:
                            pointees, member, root_ref = field_chan
                            target_id, fact = member.id, member.type
                            self.pinned.update(
                                p.id
                                for p in pointees
                                if not p.id.endswith("/pointee")
                            )
                            self._pin_member_type(member)
                            # A receive reads the pointee's contents —
                            # the full deref union (folded field-store
                            # deps, escaped bindings, indirect writes)
                            # plus every queue the member may alias
                            # (`p.C = ch` makes `<-p.C` observe
                            # `ch <- x`).
                            base_deps = self._deref_read_deps(
                                root_ref.binding_id, params, locals_
                            ) | self._field_chan_deps(
                                member.id, locals_, params
                            )
                        self._pin_fact_identities(fact)
                        transfers.append(
                            CallTransfer(
                                FileSpan(
                                    self.current_file,
                                    node.start_byte,
                                    node.end_byte,
                                ),
                                target_id,
                                (),
                                frozenset(),
                                imported=True,
                            )
                        )
                        return self.indirect_writes | base_deps
                    if binding.id in params or (
                        binding.id in self.external_chan_locals
                    ):
                        # `<-ch` on a channel parameter or a
                        # callee-produced queue reads state shared
                        # beyond this function — external state like
                        # a bound pointer's memory: the name's own
                        # provenance carries provenance,
                        # `indirect_writes` makes own sends
                        # observable, and the imported transfer
                        # keeps `effects` honest.
                        transfers.append(
                            CallTransfer(
                                FileSpan(
                                    self.current_file,
                                    node.start_byte,
                                    node.end_byte,
                                ),
                                binding.id,
                                (),
                                frozenset(),
                                imported=True,
                            )
                        )
                        slot = locals_.get(binding.id)
                        if slot is None:
                            # A rebound name keeps its merged queue
                            # set in `locals_` (`if c { ch = q }` —
                            # either queue may serve the receive);
                            # only a never-rebound param reads its
                            # bare ordinal.
                            slot = (
                                frozenset({params[binding.id]})
                                if binding.id in params
                                else frozenset()
                            )
                        return slot | self.indirect_writes
                    return locals_.get(binding.id, frozenset())
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
                    # `&h` hands the callee a writable alias — after
                    # `mutate(&h)` the name may hold a function the
                    # alias record never saw, so `h(x)` can no
                    # longer resolve through it. The literal's own
                    # records stay as a (conservative) alternative —
                    # the marker keeps the external model on top.
                    self.func_aliases.pop(ref.binding_id, None)
                    self.opaque_callees.add(ref.binding_id)
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
                not in {
                    "direct_local",
                    "direct_import",
                    "conversion",
                    "builtin",
                    "indirect_or_selector",
                    "interface_dispatch",
                }
            ):
                raise _Unsupported("unresolved_or_opaque_call", _span(node))
            arguments_node = node.child_by_field_name("arguments")
            arguments = _children(arguments_node) if arguments_node is not None else []
            if tuple(self.node_key(arg) for arg in arguments) != tuple(
                _key3(a) for a in call.arguments
            ):
                raise _Unsupported("call_mapping_unavailable", _span(node), call.target)
            if call.kind == "interface_dispatch":
                return self._interface_dispatch_call(
                    node, call, arguments, fn, params, locals_,
                    transfers, count, depth,
                )
            if call.kind == "indirect_or_selector":
                # `h(args)` where `h` names a bound function literal —
                # the record itself cannot say which shape the callee
                # has, so the callee identifier's binding decides.
                return self._bound_closure_call(
                    node, arguments, fn, params, locals_, transfers,
                    count, depth,
                )
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
                if name == b"new":
                    # `new(T)` — a pure allocation of a `*T`: its
                    # argument is a type expression, never evaluated,
                    # so the result carries no dependencies and no
                    # transfer records. Pinning the argument's named
                    # identities keeps `stale_dependents` honest; the
                    # pointer's own use-site gates (`*p`, `(*p)[i]`)
                    # classify what the pointee admits. A `struct{...}`
                    # literal names no `type` identity, so pinning
                    # reduces to each field's declared type — the
                    # pointee gates then resolve `p.F`/`(*p).F` like
                    # `var p *struct{...}` does. `make` stays
                    # opaque — its result is a composite value, which
                    # the fragment's binding model cannot hold.
                    arg = arguments[0] if len(arguments) == 1 else None
                    while (
                        arg is not None
                        and arg.type
                        in {"parenthesized_expression", "parenthesized_type"}
                    ):
                        arg = next(
                            (
                                c
                                for c in arg.named_children
                                if c.type != "comment"
                            ),
                            None,
                        )
                    pinned = (
                        self._pin_struct_fields(arg)
                        if arg is not None and arg.type == "struct_type"
                        else arg is not None and self._pin_type_node(arg)
                    )
                    if not pinned:
                        raise _Unsupported(
                            "unresolved_or_opaque_call", _span(node)
                        )
                    return frozenset()
                if name == b"make":
                    # `make(chan T[, cap])` — a fresh empty channel:
                    # the type expression pins its named identities
                    # like `new`, and a buffered capacity evaluates
                    # for calls but is not a stored value. The
                    # channel's dep set starts empty and grows by
                    # send.
                    if (
                        len(arguments) not in {1, 2}
                        or arguments[0].type != "channel_type"
                        or not self._pin_type_node(arguments[0])
                    ):
                        # `make([]func, n)`/`make(map[K]func)` —
                        # a fresh EMPTY func-element container:
                        # the type pins its named identities, a size
                        # or capacity argument evaluates for calls
                        # but is not a stored value, and the
                        # container's dep set starts empty and grows
                        # by element stores. A non-func collection
                        # still cannot bind — it stays opaque.
                        if (
                            not self._func_elem_make(node)
                            or not self._pin_func_elem_make_type(
                                arguments[0]
                            )
                        ):
                            raise _Unsupported(
                                "unresolved_or_opaque_call", _span(node)
                            )
                        for extra in arguments[1:]:
                            self.expression(
                                extra, fn, params, locals_,
                                transfers, count, depth + 1,
                            )
                        return frozenset()
                    if len(arguments) == 2:
                        self.expression(
                            arguments[1], fn, params, locals_,
                            transfers, count, depth + 1,
                        )
                    return frozenset()
                if name == b"close":
                    # `close(ch)` on a local channel — a
                    # synchronization fact the dep model does not
                    # track. Closing a channel in external state
                    # (`close(p.C)`, `close(GC)`) mutates memory the
                    # summary cannot record, so only a local
                    # channel operand admits.
                    if len(arguments) != 1:
                        raise _Unsupported(
                            "unresolved_or_opaque_call", _span(node)
                        )
                    binding = self._chan_binding(
                        arguments[0], locals_, params
                    )
                    if binding is None:
                        # `close(GC)` / `close(lib.GC)` — closing a
                        # queue in external state is a caller-visible
                        # effect recorded on the var/member's own
                        # identity, like `close` on a `chan`
                        # parameter. `close(p.C)` closes the queue
                        # a bound pointer's field names in caller
                        # memory.
                        external = self._external_chan_operand(
                            arguments[0], params
                        )
                        field_chan = (
                            self._bound_field_chan(
                                arguments[0], locals_, params
                            )
                            if external is None
                            else None
                        )
                        if external is None and field_chan is None:
                            raise _Unsupported(
                                "unresolved_or_opaque_call", _span(node)
                            )
                        if external is not None:
                            target_id, fact = external
                        else:
                            pointees, member, root_ref = field_chan
                            target_id, fact = member.id, member.type
                            self.pinned.update(
                                p.id
                                for p in pointees
                                if not p.id.endswith("/pointee")
                            )
                            self._pin_member_type(member)
                            # The operand read — resolving `p.C`
                            # reads the pointer plus every earlier
                            # indirect store, like the send's
                            # destination read.
                            self._record_read(
                                self._pointer_deps(
                                    root_ref.binding_id, params,
                                    locals_,
                                )
                                | self.indirect_writes
                            )
                        self._pin_fact_identities(fact)
                        transfers.append(
                            CallTransfer(
                                FileSpan(
                                    self.current_file,
                                    node.start_byte,
                                    node.end_byte,
                                ),
                                target_id,
                                (),
                                frozenset(),
                                imported=True,
                            )
                        )
                        return frozenset()
                    if binding.id in params or (
                        binding.id in self.external_chan_locals
                    ):
                        # `close(ch)` on a channel parameter or a
                        # callee-produced queue — the shared queue
                        # closes, a caller-visible effect the
                        # summary records on the
                        # parameter's binding identity (unlike a
                        # local close, which is an untracked
                        # synchronization fact only).
                        transfers.append(
                            CallTransfer(
                                FileSpan(
                                    self.current_file,
                                    node.start_byte,
                                    node.end_byte,
                                ),
                                binding.id,
                                (),
                                frozenset(),
                                imported=True,
                            )
                        )
                    return frozenset()
                if name == b"append":
                    # `append(fs, f)` / `append(fs, fs2...)` on a
                    # bound func-element container — the result
                    # unions the container's deps and every appended
                    # element's, and each element's func-value
                    # records adopt onto the container binding like
                    # composite literal elements do (literals
                    # recorded themselves during this eval; the
                    # identifier/selector cases adopt here). The
                    # store loop then shares the result name into
                    # the argument's backing group. Any other
                    # append stays opaque.
                    append_cont = self._func_elem_append_target(
                        node, locals_
                    )
                    if append_cont is None:
                        raise _Unsupported(
                            "unresolved_or_opaque_call", _span(node)
                        )
                    deps = self.expression(
                        arguments[0], fn, params, locals_, transfers,
                        count, depth + 1,
                    )
                    for extra in arguments[1:]:
                        element = extra
                        variadic = element.type == "variadic_argument"
                        if variadic:
                            element = next(
                                iter(element.named_children), None
                            )
                        element_id: str | None = None
                        if element is not None and element.type == (
                            "identifier"
                        ):
                            e_ref = self.references.get(
                                self.node_key(element)
                            )
                            if e_ref is not None:
                                element_id = e_ref.binding_id
                                if variadic:
                                    spread = self.bindings.get(
                                        element_id
                                    )
                                    if spread is None or not (
                                        self._func_elem_collection(
                                            spread.type
                                        )
                                    ):
                                        # `append(fs, v...)` — the
                                        # spread must name a bound
                                        # func-element container or
                                        # the appended elements'
                                        # records cannot resolve.
                                        raise _Unsupported(
                                            "unresolved_or_opaque_call",
                                            _span(node),
                                        )
                        elif (
                            element is not None
                            and element.type == "selector_expression"
                        ):
                            e_field = element.child_by_field_name(
                                "field"
                            )
                            e_fref = (
                                self.references.get(
                                    self.node_key(e_field)
                                )
                                if e_field is not None
                                else None
                            )
                            e_member = self._field_identity(e_fref)
                            if e_member is not None:
                                element_id = e_member.id
                        if (
                            element_id is not None
                            and element_id != append_cont
                        ):
                            self._adopt_element_records(
                                element_id, append_cont
                            )
                        deps |= self.expression(
                            extra, fn, params, locals_, transfers,
                            count, depth + 1,
                        )
                    # Element stores reach every name sharing the
                    # backing — the container's (new) element
                    # records union into each sharer like a store
                    # through it would.
                    for holder_id in (
                        self._func_elem_sharers(append_cont)
                        - {append_cont}
                    ):
                        self._adopt_element_records(
                            append_cont, holder_id
                        )
                    return deps
                if name not in {b"min", b"max", b"len", b"cap"}:
                    raise _Unsupported("unresolved_or_opaque_call", _span(node))
                if not arguments:
                    raise _Unsupported("unsupported_expression", _span(node))
                if name in {b"len", b"cap"}:
                    if len(arguments) != 1:
                        raise _Unsupported(
                            "unresolved_or_opaque_call", _span(node)
                        )
                    chan = self._chan_binding(
                        arguments[0], locals_, params
                    )
                    if chan is not None:
                        # `len(ch)`/`cap(ch)` — the queue length and
                        # capacity are runtime state, not parameter
                        # provenance, so the result is dep-free. On a
                        # local channel it is an untracked
                        # synchronization fact like `close`; on a
                        # `chan` parameter it observes the caller's
                        # queue, recorded as an imported transfer on
                        # the parameter's binding identity.
                        if chan.id in params or (
                            chan.id in self.external_chan_locals
                        ):
                            transfers.append(
                                CallTransfer(
                                    FileSpan(
                                        self.current_file,
                                        node.start_byte,
                                        node.end_byte,
                                    ),
                                    chan.id,
                                    (),
                                    frozenset(),
                                    imported=True,
                                )
                            )
                        return frozenset()
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
            return self._direct_local_call(
                node, call.span, call.target, arguments, fn, params,
                locals_, transfers, count, depth, call=call,
            )
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
                or call.kind
                not in {
                    "direct_import",
                    "conversion",
                    "indirect_or_selector",
                }
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
            if call.kind == "indirect_or_selector":
                # `fs[i](x)` — an element call whose index is a bare
                # identifier parses as a generic instantiation
                # (`generic_type` callee); `_opaque_indirect_call`
                # decides whether the operand names a func-element
                # collection (a true `F[T](x)` stays closed).
                callee_type = node.child_by_field_name("type")
                if callee_type is None or callee_type.type != "generic_type":
                    raise _Unsupported(
                        "unsupported_expression", _span(node)
                    )
                return self._opaque_indirect_call(
                    node, callee_type, arguments, fn, params, locals_,
                    transfers, count, depth,
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

    def _direct_local_call(
        self,
        node: Any,
        span: FileSpan,
        target_id: str,
        arguments: list[Any],
        fn: Function,
        params: dict[str, int],
        locals_: dict[str, frozenset[int]],
        transfers: list[CallTransfer],
        count: list[int],
        depth: int,
        call: Any | None = None,
    ) -> frozenset[int]:
        """`G(args)` resolved against a declared same-package function —
        shared by the `direct_local` record, a function-name alias
        call (`h := G; h(args)`), and the same-package method-call
        records (`call.method` / `call.method_expr`), which carry
        G's own summary too. A `call` flagged `method` evaluates the
        selector operand as the receiver and binds it at actual
        index 0; `method_expr` takes the receiver as argument 0 so
        arity is `parameters + 1`."""
        target = self.functions.get(target_id)
        if target is None:
            raise _Unsupported("callee_unavailable", _span(node), target_id)
        receiver_deps: frozenset[int] | None = None
        receiver_node = None
        if call is not None and call.method:
            # `st.M(args)` — the receiver operand sits on the
            # selector's `operand` field and is evaluated like an
            # argument (first, per Go's call order); its deps bind
            # the callee's leading receiver parameter.
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
            receiver_node = function_node.child_by_field_name("operand")
            if receiver_node is None:
                raise _Unsupported(
                    "call_mapping_unavailable",
                    _span(node),
                    call.target,
                )
            receiver_deps = self.expression(
                receiver_node, fn, params, locals_,
                transfers, count, depth + 1,
            )
            if (
                target.receiver is not None
                and target.receiver.type.kind != "pointer"
            ):
                root = self._receiver_root_ref(receiver_node)
                root_binding = (
                    self.bindings.get(root.binding_id)
                    if root is not None
                    else None
                )
                if (
                    root_binding is not None
                    and root_binding.type.kind == "pointer"
                ):
                    # `p.Value()` on a value receiver
                    # auto-derefs — the callee reads pointee
                    # memory, and a `*p = x` store broadcasts
                    # into `indirect_writes`, not `p`'s own set.
                    receiver_deps |= self.indirect_writes
            if isinstance(receiver_deps, frozenset):
                # A receiver's value can reach an argument-position
                # callback too — `st.M(G)` calling `g(st.V)` — so
                # it joins the call's argument deps alongside the
                # syntactic arguments.
                key = self.node_key(node)
                self._call_arg_deps[key] = (
                    self._call_arg_deps.get(key, frozenset())
                    | receiver_deps
                )
            arity = len(target.parameters)
        elif call is not None and call.method_expr:
            # `T.M(st, args)` — the leading argument already IS the
            # receiver, so arity counts it.
            arity = len(target.parameters) + 1
        else:
            arity = len(target.parameters)
        if len(arguments) != arity:
            raise _Unsupported("callee_unavailable", _span(node), target_id)
        # Even unused arguments are evaluated and must have supported effects.
        actual = tuple(
            self.expression(
                arg, fn, params, locals_, transfers, count, depth + 1
            )
            for arg in arguments
        )
        if receiver_deps is not None:
            actual = (receiver_deps, *actual)
        elif (
            call is not None
            and call.method_expr
            and arguments
            and target.receiver is not None
            and target.receiver.type.kind != "pointer"
        ):
            # `T.M(p, args)` on a value receiver auto-derefs `p`
            # like `p.Value()` — the pointee contents broadcast
            # into `indirect_writes`, not `p`'s own set.
            root = self._receiver_root_ref(arguments[0])
            root_binding = (
                self.bindings.get(root.binding_id)
                if root is not None
                else None
            )
            if (
                root_binding is not None
                and root_binding.type.kind == "pointer"
            ):
                actual = (
                    actual[0] | self.indirect_writes,
                    *actual[1:],
                )
        callee = self.summarize(target_id)
        if not callee.available:
            reason = (
                "recursive_call_graph"
                if any(g.reason == "recursive_call_graph" for g in callee.gaps)
                else "callee_unsupported"
            )
            raise _Unsupported(reason, _span(node), target_id)
        assert callee.return_dependencies is not None
        result = frozenset(
            i for parameter in callee.return_dependencies for i in actual[parameter]
        )
        # The callee's declared named-type signature identities pin
        # exactly like an imported callee's: a local type's identity
        # already churns with its declaring file, while an imported one
        # (a local `func G(y lib.T)` parameter) would otherwise leave
        # this summary looking current after `T` is redeclared. A
        # method's receiver type pins the same way.
        for p in (
            *((target.receiver,) if target.receiver is not None else ()),
            *target.parameters,
            *target.results,
        ):
            pb = self.bindings.get(p.binding_id)
            if pb is not None:
                # Func-typed signature slots (`f func(N) int64`)
                # declare their inner named types on the callee's
                # binding record, like signature_type_ids does for
                # an imported member.
                self.pinned.update(pb.signature_type_ids)
            if p.type.type_id:
                self.pinned.add(p.type.type_id)
                # `p PP` on `type PP *T` — PP's member carries the
                # pointee identity in its `elem`, which pins with
                # it exactly like the imported signature_type_ids
                # the producer now emits for the same param.
                named = self._pointee_type(p.type.type_id)
                if named is not None and named.type.kind == "pointer":
                    self._pin_fact_identities(named.type)
        # The callee's effect opacity propagates: a local callee that
        # itself performs imported transfers leaves this caller's
        # effects unbounded the same way a direct_import does.
        transfers.append(
            CallTransfer(
                span,
                target_id,
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
            stored = (
                frozenset().union(*actual)
                if actual
                else frozenset()
            )
            write_args = list(arguments)
            if receiver_node is not None:
                # `st.M()` hands the callee `&st` under a `*T`
                # receiver — stores inside `M` land in the
                # caller's `st` like an `&x` argument's do.
                write_args.append(receiver_node)
            self._store_call_writes(
                write_args, stored, locals_, params
            )
            # `st.M()` on a VALUE var auto-takes `&st`, so the
            # operand node isn't `&st`-shaped for
            # `_store_call_writes` to find — fold the write deps
            # into the receiver binding directly when the callee's
            # receiver is a pointer. `T.M(st, args)` auto-refs the
            # same way through argument 0.
            receiver_operand = (
                receiver_node
                if receiver_node is not None
                else (
                    arguments[0]
                    if call is not None
                    and call.method_expr
                    and arguments
                    else None
                )
            )
            if (
                receiver_operand is not None
                and target.receiver is not None
                and target.receiver.type.kind == "pointer"
            ):
                # Resolve the operand's ROOT identifier — `st.M()`
                # gives `st`, `s.A.Set(x)` gives `s` (a field
                # receiver auto-takes `&s.A`, whose stores land in
                # the root's conflated set), `(*p).M()` gives `p`.
                rref = self._receiver_root_ref(receiver_operand)
                rbinding = (
                    self.bindings.get(rref.binding_id)
                    if rref is not None
                    else None
                )
                if rref is not None and rbinding is not None and (
                    rref.binding_id in locals_
                    or rref.binding_id in params
                ):
                    if rbinding.type.kind == "pointer":
                        # `(*p).Set(x)` / `p.Set(x)` writes through
                        # the pointer — pointee memory, broadcast
                        # into `indirect_writes` like `*p = v`,
                        # plus every escaped binding it may aim at.
                        self.indirect_writes |= stored
                        for escaped_id in self.escaped:
                            if (
                                escaped_id in locals_
                                or escaped_id in params
                            ):
                                esc_base = (
                                    locals_.get(escaped_id)
                                    if escaped_id in locals_
                                    else frozenset(
                                        {params[escaped_id]}
                                    )
                                )
                                locals_[escaped_id] = (
                                    esc_base | stored
                                )
                    else:
                        base = (
                            locals_.get(rref.binding_id)
                            if rref.binding_id in locals_
                            else frozenset(
                                {params[rref.binding_id]}
                            )
                        )
                        locals_[rref.binding_id] = base | stored
            # A callee's ops on an external channel — `GC <- x`,
            # `<-lib.VC` — mutate a queue the caller shares:
            # `G(ch)`'s sends already broadcast through the arg
            # binding, but `GC` is no argument, so the call's
            # deps broadcast into `indirect_writes` for a later
            # `<-GC`/`range GC` to observe.
            if self._calls_touch_external_chan(callee.calls):
                self.indirect_writes |= stored
                if self._calls_touch_external_chan(
                    callee.calls, self._chan_chan_id
                ):
                    # `cc <- q` inside the callee handed a `chan`
                    # argument's queue to the outer queue's
                    # domain — promote the argument roots like an
                    # imported chan-result bind does, so sends a
                    # received channel performs stay connected
                    # to `<-q`.
                    self._promote_chan_arg_roots(
                        arguments, "", locals_, params
                    )
        return result

    def _propagate_func_alias(
        self,
        dest_id: str,
        src_id: str | None,
        aliases_before: dict[str, str],
        params: dict[str, int],
        conditional: bool,
    ) -> None:
        """Identifier-RHS store bookkeeping for function-name aliases:
        `h := G` binds a declared function, `h2 := h` inherits a
        recorded alias, and any other RHS clears one. A maybe-skipped
        store can only record an alias when the name already resolves
        to the same target — otherwise both models clear and the call
        falls back to the opaque external callee."""
        dest_binding = self.bindings.get(dest_id)
        if dest_binding is not None and self._package_level(
            dest_binding
        ):
            # A package-level `var Alias = Id` is mutable by any
            # caller — its call stays the opaque external model.
            return
        src_binding = (
            self.bindings.get(src_id) if src_id is not None else None
        )
        target = (
            src_id
            if (
                src_binding is not None
                and src_binding.kind == "function"
            )
            else (
                aliases_before.get(src_id)
                if src_id is not None
                else None
            )
        )
        if target is None:
            self.func_aliases.pop(dest_id, None)
            return
        ambiguous = (conditional or self._may_skip > 0) and (
            self.func_aliases.get(dest_id) != target
            or dest_id in self.closure_captures
            or dest_id in self.pointee_closures
            or dest_id in self.closure_writes
            or dest_id in self.closure_star_writes
            or dest_id in self.closure_inner_calls
            or dest_id in self.opaque_callees
            or dest_id in params
        )
        if ambiguous:
            # Either the old or the new callee may run — the name
            # resolves opaquely: keep every closure record so the call
            # folds the literal alternatives' captures and write
            # targets, and mark the name so the external model still
            # applies to the rest.
            self.func_aliases.pop(dest_id, None)
            self.opaque_callees.add(dest_id)
        else:
            self.func_aliases[dest_id] = target
            self.opaque_callees.discard(dest_id)
            self.closure_captures.pop(dest_id, None)
            self.pointee_closures.discard(dest_id)
            self.closure_writes.pop(dest_id, None)
            self.closure_star_writes.discard(dest_id)
            self.closure_inner_calls.discard(dest_id)

    def _record_bound_method(
        self,
        bid: str,
        mv: tuple[str, str | None] | None,
        params: dict[str, int],
        locals_: dict[str, frozenset[int]],
    ) -> None:
        """Record (or clear) a bound-method record under `bid` and
        FREEZE the receiver's current dep set: a Go method value
        copies its receiver at bind time, so a `s = …` reseat before
        `f(args)` must not shift what the call resolves."""
        if mv is None:
            self._drop_bound_method(bid)
            return
        self.bound_method_values[bid] = mv
        recv_id = mv[1]
        if recv_id is None:
            self.bound_method_receiver_deps.pop(bid, None)
        elif recv_id in locals_:
            self.bound_method_receiver_deps[bid] = locals_[recv_id]
        elif recv_id in params:
            self.bound_method_receiver_deps[bid] = frozenset(
                {params[recv_id]}
            )
        else:
            self.bound_method_receiver_deps.pop(bid, None)

    def _drop_bound_method(
        self, bid: str, conditional: bool = False
    ) -> None:
        """Clear a bound-method record. A conditional drop leaves the
        old method value live on the untaken path — mark its receiver
        escaped so a later opaque call still folds the callee's
        possible writes back into it."""
        old = self.bound_method_values.pop(bid, None)
        self.bound_method_receiver_deps.pop(bid, None)
        if conditional and old is not None and old[1] is not None:
            self.escaped.add(old[1])

    def _drop_func_value_records(
        self, bid: str, conditional: bool = False
    ) -> None:
        """Clear every func-value record a reused name carried —
        captured bindings, pointee/write marks, bound method values
        and the function alias — so a call through the name resolves
        the NEW value instead of a stale literal or method pair.

        A conditional drop leaves the untaken path's OLD value live:
        the name becomes opaque (the external model folds its own dep
        set, the escaped bindings and indirect writes) but KEEPS its
        literal records — the call then resolves the untaken literal's
        captures and write targets with CURRENT deps instead of the
        rebind-time ones, and a captured binding read-only by the old
        literal never becomes a write candidate."""
        if conditional:
            self.opaque_callees.add(bid)
            self._drop_bound_method(bid, True)
            self.func_aliases.pop(bid, None)
            return
        self.opaque_callees.discard(bid)
        self._drop_bound_method(bid)
        self.closure_captures.pop(bid, None)
        self.pointee_closures.discard(bid)
        self.closure_writes.pop(bid, None)
        self.closure_star_writes.discard(bid)
        self.closure_inner_calls.discard(bid)
        self.func_aliases.pop(bid, None)

    def _func_alias_bind(self, node: Any) -> frozenset[int]:
        """`h := G` / `h = G` / `var h = G` — a declared function
        name read as a store value, or `H(G, args)` — a function
        name read as a call argument.

        A function-name identifier sitting in the value position of
        a name binding admits dep-free; the store's identifier-RHS
        propagation records `func_aliases[bound] = G` so `h(...)`
        resolves through G's own summary like a `direct_local`
        call. A function name in a call's argument list also admits
        dep-free — the callee may invoke it at an unknown time, so
        the read queues a pending invocation keyed by the enclosing
        call: `expression` folds it once the call's deps are known,
        recording a transfer on G's identity and, when G's own
        effects are unbounded or touch an external channel,
        broadcasting the call's deps into `indirect_writes` for a
        later receive to observe. The binding and its signature
        identities pin too — redeclaring `G` stales the caller like
        any pinned identity. A name in any other position — a
        `return`, a computed operand, a comparison — stays closed.
        """
        parent = node.parent
        while parent is not None and parent.type == "expression_list":
            parent = parent.parent
        name_node = None
        if parent is not None and parent.type in {
            "short_var_declaration",
            "assignment_statement",
        }:
            left = parent.child_by_field_name("left")
            right = parent.child_by_field_name("right")
            if left is not None and right is not None:
                names = _children(left)
                values = _children(right)
                index = next(
                    (i for i, v in enumerate(values) if v == node),
                    None,
                )
                if index is not None and index < len(names):
                    name_node = names[index]
        elif parent is not None and parent.type == "var_spec":
            names = []
            values = []
            for i, c in enumerate(parent.children):
                field = parent.field_name_for_child(i)
                if field == "name":
                    names.append(c)
                elif field == "value":
                    values.extend(_children(c))
            index = next(
                (i for i, v in enumerate(values) if v == node), None
            )
            if index is not None and index < len(names):
                name_node = names[index]
        if name_node is not None and name_node.type == "identifier":
            return frozenset()
        # `return G` — a func-typed result hands the declared
        # function back to the caller: the read is dep-free like the
        # store positions, and the caller binds the result name as
        # an opaque func value whose calls resolve through the
        # func-value path (the result's identity does not ride the
        # summary, so no pin records here).
        if parent is not None and parent.type == "return_statement":
            return frozenset()
        # `H(G, args)` — the name sits in a call's argument list.
        # The call record's span is the `call_expression` parent of
        # the argument list, so the record itself proves the
        # position. The possible invocation is queued for the call's
        # own fold (the call's dep set is still being built here —
        # later arguments have not evaluated yet), and G's binding
        # plus its signature identities pin for staleness.
        parent = node.parent
        call_node = (
            parent.parent if parent is not None else None
        )
        call = (
            self.calls.get(self.node_key(call_node))
            if parent is not None
            and parent.type == "argument_list"
            and call_node is not None
            and call_node.type == "call_expression"
            else None
        )
        if call is None:
            raise _Unsupported("non_parameter_reference", _span(node))
        ref = self.references.get(self.node_key(node))
        binding = (
            self.bindings.get(ref.binding_id)
            if ref is not None
            else None
        )
        if binding is not None:
            self.pinned.add(binding.id)
            if binding.type is not None:
                self._pin_fact_identities(binding.type)
            self.pinned.update(binding.signature_type_ids)
            self._func_arg_invocations.setdefault(
                self.node_key(call_node), []
            ).append((node, binding.id))
        return frozenset()

    def _func_literal_capture(
        self,
        node: Any,
        params: dict[str, int],
        locals_: dict[str, frozenset[int]],
    ) -> tuple[
        frozenset[int],
        set[str],
        bool,
        set[str],
        bool,
        bool,
    ]:
        """Free-variable scan of a `func` literal: (deps, captured
        binding ids, whether any capture is a pointer, enclosing-scope
        bindings the body writes, whether it writes through `*p`,
        whether it contains a call).

        A call or a write inside the literal no longer closes it: the
        body cannot sequence at bind time, so the call site models the
        invocation as an opaque effectful callee — the write targets
        (`x = e`, `p.V = e`, `*p = e`) and the inner-call flag ride
        out in the returned record. A send, `go`, `defer` or `close`
        still stays closed: the queue/concurrency effect has no
        place to land."""
        deps: frozenset[int] = frozenset()
        captured: set[str] = set()
        captures_pointer = False
        writes: set[str] = set()
        star_write = False
        has_call = False
        ptr_alias: dict[str, set[str]] = {}
        # The DFS below pops children in reverse order, so a use can
        # scan before its declaration — collect `p := &x` pointer
        # aliases in a separate pass first. A pointee set keeps every
        # RHS a name may hold (reassignment unions, never replaces).
        alias_stack = [node]
        while alias_stack:
            cur = alias_stack.pop()
            alias_stack.extend(_children(cur))
            if cur.type == "var_spec":
                vnames = [
                    c
                    for i, c in enumerate(cur.children)
                    if cur.field_name_for_child(i) == "name"
                ]
                vvals = [
                    c
                    for i, c in enumerate(cur.children)
                    if cur.field_name_for_child(i) == "value"
                ]
                vlefts = [n for n in vnames]
                vrights: list[Any] = []
                for v in vvals:
                    vrights.extend(_children(v))
                if len(vlefts) == len(vrights):
                    for li, lnode in enumerate(vlefts):
                        if lnode.type != "identifier":
                            continue
                        lb = self.bindings_by_span.get(
                            self.node_key(lnode)
                        )
                        if lb is None:
                            continue
                        rnode = vrights[li]
                        while (
                            rnode.type == "parenthesized_expression"
                        ):
                            rnode = next(
                                (
                                    c
                                    for c in rnode.named_children
                                    if c.type != "comment"
                                ),
                                rnode,
                            )
                            if (
                                rnode.type
                                == "parenthesized_expression"
                            ):
                                continue
                            break
                        if rnode.type == "unary_expression":
                            rop = rnode.child_by_field_name(
                                "operator"
                            )
                            operand = (
                                rnode.child_by_field_name("operand")
                                if rop is not None
                                and rop.type == "&"
                                else None
                            )
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
                                operand is not None
                                and operand.type == "identifier"
                            ):
                                rref = self.references.get(
                                    self.node_key(operand)
                                )
                                if rref is not None:
                                    ptr_alias.setdefault(
                                        lb.id, set()
                                    ).add(rref.binding_id)
                                    self.escaped.add(
                                        rref.binding_id
                                    )
                continue
            if cur.type in {
                "short_var_declaration",
                "assignment_statement",
            }:
                left = cur.child_by_field_name("left")
                right = cur.child_by_field_name("right")
                if left is None or right is None:
                    continue
                lefts = _children(left)
                rights = _children(right)
                if len(lefts) != len(rights):
                    continue
                for li, lnode in enumerate(lefts):
                    if lnode.type != "identifier":
                        continue
                    lb = self.bindings_by_span.get(
                        self.node_key(lnode)
                    )
                    if lb is None:
                        lref = self.references.get(
                            self.node_key(lnode)
                        )
                        lb_id = (
                            lref.binding_id if lref is not None else None
                        )
                    else:
                        lb_id = lb.id
                    if lb_id is None:
                        continue
                    rnode = rights[li]
                    while rnode.type == "parenthesized_expression":
                        rnode = next(
                            (
                                c
                                for c in rnode.named_children
                                if c.type != "comment"
                            ),
                            rnode,
                        )
                        if rnode.type == "parenthesized_expression":
                            continue
                        break
                    if rnode.type == "unary_expression":
                        rop = rnode.child_by_field_name("operator")
                        if rop is not None and rop.type == "&":
                            operand = rnode.child_by_field_name(
                                "operand"
                            )
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
                                operand is not None
                                and operand.type == "identifier"
                            ):
                                rref = self.references.get(
                                    self.node_key(operand)
                                )
                                if rref is not None:
                                    ptr_alias.setdefault(
                                        lb_id, set()
                                    ).add(rref.binding_id)
                                    # `&x` inside the literal hands
                                    # the call a pointer into
                                    # caller memory — an inner call
                                    # or `*p` write can reach it.
                                    self.escaped.add(rref.binding_id)

        stack = [node]
        while stack:
            cur = stack.pop()
            if cur.type in {
                "send_statement",
                "go_statement",
                "defer_statement",
            }:
                raise _Unsupported("unsupported_expression", _span(cur))
            if cur.type == "call_expression" or (
                self._elem_call_conversion(cur)
            ):
                # `fs[i](x)` inside the literal parses as a
                # conversion node but is a real element call —
                # side effects count like any call.
                has_call = True
            elif cur.type in {
                "assignment_statement",
                "inc_statement",
                "dec_statement",
            }:
                lhs = cur.child_by_field_name("left")
                if lhs is None:
                    # `x++` / `x--` carry no `left` field — the
                    # operand is the first named child.
                    lhs = next(
                        (
                            c
                            for c in cur.named_children
                            if c.type != "comment"
                        ),
                        None,
                    )
                if lhs is not None:
                    for wtarget in self._literal_write_targets(
                        lhs, ptr_alias
                    ):
                        writes.add(wtarget)
                    # `*p = e` / `(*p).V = e` / `(*p)++` inside the
                    # literal writes caller memory through a captured
                    # pointer — the escaped fold at the call site
                    # cannot name which binding it lands on, so flag
                    # it separately like a `*p = e` statement does.
                    lstack = [lhs]
                    while lstack:
                        lcur = lstack.pop()
                        if lcur.type == "unary_expression":
                            lop = lcur.child_by_field_name("operator")
                            if lop is not None and lop.type == "*":
                                star_write = True
                        lstack.extend(_children(lcur))
            if cur.type in {"identifier", "type_identifier"}:
                # `fs[i](x)`'s `generic_type` callee spells `fs`
                # and `i` in type position — `type_identifier` —
                # but they are still value reads when they resolve
                # to tracked bindings. A real type name (`T` in
                # `var v T`) carries no value read, so it is
                # skipped rather than treated as an unbound dep.
                ref = self.references.get(self.node_key(cur))
                if ref is not None and ref.kind != "universe":
                    bid = ref.binding_id
                    # `locals_` wins over the parameter ordinal: a
                    # reassigned parameter (`x = g()` or a `G(&x, y)`
                    # call fold) carries its CURRENT deps there —
                    # reading `params` first would report the stale
                    # pre-assignment set.
                    if bid in locals_:
                        deps |= locals_[bid]
                        captured.add(bid)
                        binding = self.bindings.get(bid)
                        captures_pointer |= (
                            binding is not None
                            and binding.type.kind == "pointer"
                        )
                    elif bid in params:
                        deps |= frozenset({params[bid]})
                        captured.add(bid)
                        binding = self.bindings.get(bid)
                        captures_pointer |= (
                            binding is not None
                            and binding.type.kind == "pointer"
                        )
                    elif cur.type == "type_identifier":
                        # A type name in type position — not a
                        # value read.
                        pass
                    else:
                        binding = self.bindings.get(bid)
                        if binding is not None and (
                            binding.kind == "function"
                            or (
                                getattr(
                                    binding.span,
                                    "file",
                                    self.current_file,
                                )
                                == self.current_file
                                and (
                                    node.start_byte
                                    <= binding.span.start
                                    <= node.end_byte
                                )
                            )
                        ):
                            # A declared function name (`G` in
                            # `return G(x)`) is a resolvable callee,
                            # not a captured value; a literal-internal
                            # binding needs no record either.
                            continue
                        raise _Unsupported(
                            "binding_unavailable", _span(cur)
                        )
            stack.extend(_children(cur))
        return (
            deps,
            captured,
            captures_pointer,
            writes,
            star_write,
            has_call,
        )

    def _literal_write_targets(
        self, lhs: Any, ptr_alias: dict[str, set[str]] | None = None
    ) -> set[str]:
        """Enclosing-scope binding ids an assignment LHS may write.

        `x = e` / `x++` writes `x` itself; `s.V = e` writes the
        captured aggregate `s`; `(*p).V = e` / `a[i] = e` write
        through the operand binding. Literal-internal targets (a
        name declared inside the literal) never leave the body and
        are skipped; a `*p` unary target is reported separately by
        the `star_write` flag — unless `ptr_alias` (a `p := &x`
        collected before the scan) names the pointee, in which case
        the write lands on it directly. A base identifier that is
        itself a pointer alias (`p := &q`, then `p.V = e`) folds
        into the aliased pointee too."""
        targets: set[str] = set()
        alias = ptr_alias or {}

        def _chase(bid: str) -> set[str]:
            out = {bid}
            seen = {bid}
            frontier = list(alias.get(bid, ()))
            while frontier:
                cur = frontier.pop()
                if cur in seen:
                    continue
                seen.add(cur)
                out.add(cur)
                frontier.extend(alias.get(cur, ()))
            return out

        for name in lhs.named_children:
            if name.type == "comment":
                continue
            node = name
            while node.type in {
                "parenthesized_expression",
                "selector_expression",
                "index_expression",
            }:
                node = node.children[0]
            if node.type == "unary_expression":
                # `*p = e` — resolved through a `p := &x` alias when
                # one exists; the star_write flag still covers the
                # unresolvable case.
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
                if operand is not None and operand.type == "identifier":
                    ref = self.references.get(self.node_key(operand))
                    if ref is not None and ref.binding_id in alias:
                        targets |= _chase(ref.binding_id) - {
                            ref.binding_id
                        }
                continue
            if node.type != "identifier":
                continue
            ref = self.references.get(self.node_key(node))
            if ref is not None:
                targets |= _chase(ref.binding_id)
        return targets

    def _func_literal(
        self,
        node: Any,
        params: dict[str, int],
        locals_: dict[str, frozenset[int]],
    ) -> frozenset[int]:
        """`func(...) T { ... }` — a deferred body admitted by
        conservative free-variable capture.

        The literal's statements never sequence, so the literal's
        deps are the union of every enclosing-scope binding it
        references — what `h()`'s result depends on. A call inside
        the literal defers an effect the sequencing model cannot
        place, a write targets state the caller can observe out of
        order, and a reference to anything but the enclosing
        function's own params/locals (package vars, imported
        members, fields the literal cannot pin) reads storage the
        capture cannot describe — all stay closed. Names declared
        inside the literal (its own params and locals) are not
        captured: their span sits inside the literal's."""
        (
            deps,
            captured,
            captures_pointer,
            writes,
            star_write,
            has_call,
        ) = self._func_literal_capture(node, params, locals_)
        # Find the name this literal binds (`h := func()...`,
        # `var h = func()...`, `h = func()...`) and record which
        # enclosing bindings it captured, so `h()` can resolve
        # each capture's deps at CALL time — the dep set frozen
        # here goes stale when a captured local is reassigned
        # between the literal and the call. Record unconditionally:
        # rebinding `h` to a literal that captures nothing must
        # clear a capture set the earlier literal left behind.
        # A literal with no bound name needs no record: only a
        # bare identifier call admits, so the value can never be
        # invoked through this summary. `node.parent` is the
        # expression_list wrapper — climb past it (and any further
        # list nesting) to the declaring statement. A literal nested
        # in a `[]func`/`[N]func` composite (`fs := []func(){…}`)
        # binds through the container name — climb past the literal
        # wrappers too, so the element's captures record under the
        # container binding the `fs[k]()` call reads. A literal in
        # an `append(fs, func(){…})` argument climbs through the
        # argument list the same way — it stores an element into the
        # container the call extends.
        parent = node.parent
        in_composite = False
        # A literal stored through an index or `append` lands in the
        # container's CURRENT backing, which the share group still
        # reads — a composite-literal element instead initializes
        # the NEW backing the name is about to receive, so its
        # records must not reach the old backing's sharers.
        into_backing = False
        while parent is not None and parent.type in {
            "expression_list",
            "literal_value",
            "literal_element",
            "keyed_element",
            "composite_literal",
            "argument_list",
        }:
            if parent.type == "composite_literal":
                in_composite = True
            parent = parent.parent
        name_node = None
        if parent is not None and parent.type in {
            "short_var_declaration",
            "assignment_statement",
        }:
            left = parent.child_by_field_name("left")
            right = parent.child_by_field_name("right")
            if left is not None and right is not None:
                names = _children(left)
                values = _children(right)
                index = next(
                    (i for i, v in enumerate(values) if v == node),
                    None,
                )
                if index is None and in_composite:
                    # The literal nests inside one composite value —
                    # `fs := []func(){…}` binds the name whose RHS
                    # node CONTAINS this literal.
                    index = next(
                        (
                            i
                            for i, v in enumerate(values)
                            if v.start_byte <= node.start_byte
                            and node.end_byte <= v.end_byte
                        ),
                        None,
                    )
                if index is not None and index < len(names):
                    name_node = names[index]
        elif parent is not None and parent.type == "var_spec":
            names = [
                c
                for i, c in enumerate(parent.children)
                if parent.field_name_for_child(i) == "name"
            ]
            values = [
                c
                for i, c in enumerate(parent.children)
                if parent.field_name_for_child(i) == "value"
            ]
            index = next(
                (i for i, v in enumerate(values) if v == node), None
            )
            if index is None and in_composite:
                index = next(
                    (
                        i
                        for i, v in enumerate(values)
                        if v.start_byte <= node.start_byte
                        and node.end_byte <= v.end_byte
                    ),
                    None,
                )
            if index is not None and index < len(names):
                name_node = names[index]
        bound_id: str | None = None
        if name_node is not None and name_node.type == "identifier":
            binding = self.bindings_by_span.get(
                self.node_key(name_node)
            )
            bound_id = (
                binding.id
                if binding is not None
                else (
                    self.references[self.node_key(name_node)].binding_id
                    if self.node_key(name_node) in self.references
                    else None
                )
            )
        elif (
            name_node is not None
            and name_node.type == "selector_expression"
        ):
            # `s.f = func() { …x… }` stores the literal into a
            # func-typed FIELD — record under the field member's
            # identity so the opaque `s.f(...)` call can re-resolve
            # the captures at call time.
            member = self._field_member(name_node)
            if (
                member is not None
                and member.kind in {"var", "variable"}
                and member.type is not None
                and member.type.kind == "function"
            ):
                bound_id = member.id
        elif (
            name_node is not None
            and name_node.type == "index_expression"
        ):
            # `fs[i] = func() { …x… }` stores the literal into a
            # func-element container's slot — record under the
            # container's binding like a composite literal element,
            # so `fs[k]()` re-resolves the captures at call time.
            operand = name_node.child_by_field_name("operand")
            while (
                operand is not None
                and operand.type == "parenthesized_expression"
            ):
                operand = operand.child_by_field_name("operand")
            container_ref = (
                self.references.get(self.node_key(operand))
                if operand is not None
                and operand.type == "identifier"
                else None
            )
            container = (
                self.bindings.get(container_ref.binding_id)
                if container_ref is not None
                else None
            )
            if container is not None and self._func_elem_collection(
                container.type
            ):
                bound_id = container.id
                in_composite = True
                into_backing = True
            elif operand is not None:
                # `fm[k][i] = func(){…}` — the nested store's
                # elements conflate under the root binding, so the
                # literal records there like `fm[k] = lit` does.
                nested = self._func_elem_nested_operand(operand)
                if nested is not None:
                    bound_id = nested[0]
                    in_composite = True
                    into_backing = True
        elif parent is not None and parent.type == "call_expression":
            # `append(fs, func(){…})` — the literal is an appended
            # element of the argument container; record under its
            # binding like a composite element.
            bound_id = self._func_elem_append_target(parent, locals_)
            if bound_id is not None:
                in_composite = True
                into_backing = True
        if bound_id is not None:
            may_skip = self._conditional or self._may_skip > 0
            if in_composite:
                # An element literal inside `fs := []func(){…}` —
                # the container may hold other elements with their
                # own captures, so union rather than replace. The
                # container's element set is never cleared either:
                # `fs[k]()` resolves through the opaque index call
                # and reads this unioned record.
                # The store lands in the container's CURRENT backing,
                # so every eval-time sharer gets the record too —
                # `a, a[0] = b, lit` stores `lit` into `a`'s old
                # backing, and a later `a = b` reseat clearing `a`'s
                # records must not drop it from the sharers (`a2`)
                # that still read that backing.
                composite_targets = {bound_id} | (
                    self._func_elem_groups.get(bound_id, set())
                    if into_backing
                    else set()
                )
                for target_id in composite_targets:
                    self.closure_captures[target_id] = (
                        self.closure_captures.get(
                            target_id, frozenset()
                        )
                        | frozenset(captured)
                    )
                    self.closure_writes[target_id] = (
                        self.closure_writes.get(
                            target_id, frozenset()
                        )
                        | frozenset(writes)
                    )
                if star_write:
                    self.closure_star_writes.update(composite_targets)
                if has_call:
                    self.closure_inner_calls.update(composite_targets)
            elif may_skip and bound_id in self.func_aliases:
                # A literal on a maybe-taken path over a
                # function-name alias leaves the callee's value
                # path-dependent — union the literal's records so
                # the call folds this alternative's captures and
                # write targets, and mark the name opaque so the
                # untaken alias's callee still resolves through
                # the external model.
                self.closure_captures[bound_id] = (
                    self.closure_captures.get(bound_id, frozenset())
                    | frozenset(captured)
                )
                self.closure_writes[bound_id] = (
                    self.closure_writes.get(bound_id, frozenset())
                    | frozenset(writes)
                )
                if star_write:
                    self.closure_star_writes.add(bound_id)
                if has_call:
                    self.closure_inner_calls.add(bound_id)
                self.func_aliases.pop(bound_id, None)
                self.opaque_callees.add(bound_id)
            elif may_skip and bound_id in self.closure_captures:
                # A maybe-skipped rebind keeps the old literal's
                # captures on the path that does not run it —
                # union like `_store` unions the binding's deps.
                self.closure_captures[bound_id] = (
                    self.closure_captures[bound_id]
                    | frozenset(captured)
                )
                self.closure_writes[bound_id] = (
                    self.closure_writes.get(bound_id, frozenset())
                    | frozenset(writes)
                )
                if star_write:
                    self.closure_star_writes.add(bound_id)
                if has_call:
                    self.closure_inner_calls.add(bound_id)
            elif may_skip and (
                bound_id in self.bound_method_values
                or bound_id in locals_
                or bound_id in params
            ):
                # A maybe-skipped literal over a NON-literal value —
                # a parameter callback (`f := cb`), a call result
                # (`f := mk()`), a declared zero value or a bound
                # method — leaves the old callee live on the untaken
                # path. Union the literal's records with whatever the
                # name already described and mark it opaque: the call
                # then folds the literal alternatives' captures and
                # write targets resolved at CALL time, while the
                # external model covers the non-literal alternative.
                self.closure_captures[bound_id] = (
                    self.closure_captures.get(bound_id, frozenset())
                    | frozenset(captured)
                )
                self.closure_writes[bound_id] = (
                    self.closure_writes.get(bound_id, frozenset())
                    | frozenset(writes)
                )
                if star_write:
                    self.closure_star_writes.add(bound_id)
                if has_call:
                    self.closure_inner_calls.add(bound_id)
                self._drop_bound_method(bound_id, True)
                self.func_aliases.pop(bound_id, None)
                self.opaque_callees.add(bound_id)
            else:
                self.closure_captures[bound_id] = frozenset(captured)
                self.closure_writes[bound_id] = frozenset(writes)
                if star_write:
                    self.closure_star_writes.add(bound_id)
                else:
                    self.closure_star_writes.discard(bound_id)
                if has_call:
                    self.closure_inner_calls.add(bound_id)
                else:
                    self.closure_inner_calls.discard(bound_id)
                # An unconditional literal bind resolves the name
                # to this literal — a function alias or opaque mark
                # an earlier rebind left behind no longer applies.
                self.func_aliases.pop(bound_id, None)
                self.opaque_callees.discard(bound_id)
            if captures_pointer:
                self.pointee_closures.add(bound_id)
            elif not may_skip:
                # Rebinding `h` to a literal that captures no
                # pointer clears the flag the earlier literal set
                # — a conditional rebind keeps it for the path
                # that keeps the old literal.
                self.pointee_closures.discard(bound_id)
        return deps

    def _bound_closure_call(
        self,
        node: Any,
        arguments: list[Any],
        fn: Function,
        params: dict[str, int],
        locals_: dict[str, frozenset[int]],
        transfers: list[CallTransfer],
        count: list[int],
        depth: int,
    ) -> frozenset[int]:
        """`h(args)` where `h` names a bound function literal.

        Only a bare-identifier callee whose binding is
        function-typed resolves through a bound literal — a
        parenthesized callee unwraps to the same shape, while a
        selector (`s.f()`) or computed (`m[k]()`) callee runs as an
        opaque external call like a func-typed parameter does. The
        result resolves the literal's captured bindings
        at the CALL site — `closure_captures` keeps the binding ids
        so a captured local reassigned after the literal reports
        its current deps — plus the argument's own evaluation; it
        also unions
        `indirect_writes`, since a literal may read caller memory
        through a captured pointer and aliased pointee stores the
        capture cannot name affect what it observes (an
        over-approximation when the literal never dereferences — the
        bind site does not record which literals do).
        """
        callee = node.child_by_field_name("function")
        while (
            callee is not None
            and callee.type == "parenthesized_expression"
        ):
            callee = next(
                (
                    c
                    for c in callee.named_children
                    if c.type != "comment"
                ),
                None,
            )
        if callee is not None and callee.type == "func_literal":
            # `func(...) T { ... }(args)` — the literal IS the
            # callee, known at this point like a bound literal's.
            return self._immediate_literal_call(
                node, callee, arguments, fn, params, locals_,
                transfers, count, depth,
            )
        if callee is not None and callee.type != "identifier":
            # `s.f(args)` / `m[k](args)` — the callee is read through
            # a field or an index, so which function it holds is
            # unknowable here: opaque external call like a
            # func-typed parameter, except the callee's own read is
            # the operand expression's deps.
            return self._opaque_indirect_call(
                node, callee, arguments, fn, params, locals_,
                transfers, count, depth,
            )
        ref = (
            self.references.get(self.node_key(callee))
            if callee is not None
            else None
        )
        binding = (
            self.bindings.get(ref.binding_id)
            if ref is not None else None
        )
        package_var = (
            binding is not None
            and binding.kind == "variable"
            and self._package_level(binding)
        )
        if (
            binding is None
            or binding.type.kind != "function"
            or (
                ref.binding_id not in locals_
                and ref.binding_id not in params
                and not package_var
            )
        ):
            # Only a function-local callee or a package-level `var`
            # admits: a package-level `var Alias = Id` can be
            # reassigned by any caller, so invoking it is an opaque
            # external call below — a function-typed package var
            # reads external state dep-free like a member read and
            # always records the external effect (its callee is
            # unknown to the caller).
            raise _Unsupported("unsupported_expression", _span(node))
        bound_mv = self.bound_method_values.get(ref.binding_id)
        if bound_mv is not None:
            return self._bound_method_call(
                node, arguments, bound_mv, fn, params, locals_,
                transfers, count, depth,
                frozen_recv=self.bound_method_receiver_deps.get(
                    ref.binding_id
                ),
            )
        alias_target = self.func_aliases.get(ref.binding_id)
        if alias_target is not None:
            # `h := G` / `h = G` bound this name to a declared
            # function — `h(args)` resolves through G's own summary
            # exactly like a `direct_local` call record does.
            alias_call = self.calls.get(self.node_key(node))
            return self._direct_local_call(
                node,
                alias_call.span if alias_call is not None
                else FileSpan(
                    self.current_file,
                    node.start_byte,
                    node.end_byte,
                ),
                alias_target, arguments, fn, params, locals_,
                transfers, count, depth,
            )
        captured = self.closure_captures.get(ref.binding_id)
        # The callee is opaque when it has no captured literal OR when
        # it is a parameter: a branch-bound literal under a param
        # (`if b { f = func()... }`) still leaves the caller's own
        # callback on the untaken path, so a param callee is always
        # external-capable. A name marked by a maybe-skipped rebind
        # (`f := cb; if b { f = func()... }`) is opaque the same way —
        # its records still describe the literal alternatives the call
        # folds in.
        external = (
            captured is None
            or ref.binding_id in params
            or ref.binding_id in self.opaque_callees
        )
        if captured is not None:
            # Resolve each captured binding's deps at the call site —
            # reassignments between the literal and the call move
            # what the call actually reads.
            deps = self._captured_current_deps(captured, params, locals_)
        else:
            deps = frozenset()
        # The callee name itself reads its CURRENT deps — `f = g`
        # reseats `f` to g's dep set, and a branch-bound literal keeps
        # the parameter ordinal in the joined set. (A local
        # literal-bound callee skips this: `locals_[h]` holds the
        # literal-time dep set, which the captured resolution above
        # already supersedes with the CURRENT ones.)
        callee_deps: frozenset[int] = frozenset()
        if external:
            if ref.binding_id in locals_:
                callee_deps = locals_[ref.binding_id]
            elif ref.binding_id in params:
                callee_deps = frozenset({params[ref.binding_id]})
        deps |= callee_deps | self.indirect_writes
        # A literal that captures a `chan` parameter may `<-ch` inside —
        # receiving consumes a queue the caller shares, an external
        # effect just like a captured pointer's deref. (A captured
        # *local* channel's queue is local state, like `<-ch` at
        # statement level — no external record.) `send_statement` and
        # `close` are closed inside literals, so receive-side effects
        # are the only ones a channel capture can hide.
        chan_captured_external = any(
            (
                self._chan_root(cbid) in params
                or self._chan_root(cbid)
                in self.external_chan_locals
            )
            and (
                self._scalar_chan_binding(cbid)
                or self._chan_chan_fact(
                    getattr(
                        self.bindings.get(cbid), "type", None
                    )
                )
            )
            for cbid in (captured or ())
        )
        if ref.binding_id in self.pointee_closures or external:
            # The call may read caller memory — a pointer-captured
            # literal through its capture, an opaque external callee
            # through a pointer argument — so it reads like a `*p`
            # read: union the escaped bindings' current deps (the
            # pointer may alias any `&x`-escaped binding — `p := &a;
            # a = y; h()` observes `y`).
            for escaped_id in self.escaped:
                if escaped_id in locals_:
                    deps |= locals_[escaped_id]
                elif escaped_id in params:
                    deps |= frozenset({params[escaped_id]})
        writes = self.closure_writes.get(
            ref.binding_id, frozenset()
        )
        star_write = ref.binding_id in self.closure_star_writes
        inner_calls = ref.binding_id in self.closure_inner_calls
        if (
            ref.binding_id in self.pointee_closures
            or chan_captured_external
            or external
            or writes
            or star_write
            or inner_calls
        ):
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
        if external and binding.type is not None:
            # An external callee's DECLARED type identity pins like
            # any signature type: `type MyFn func(...)` in another
            # file must flag the caller when it regenerates, same
            # as the var's own binding identity does. Its inner
            # signature types (`func(N) int64`) ride on the binding's
            # signature_type_ids — the func fact itself holds none.
            self._pin_fact_identities(binding.type)
            self.pinned.update(binding.signature_type_ids)
        arg_deps: frozenset[int] = frozenset()
        for arg in arguments:
            arg_deps |= self.expression(
                arg, fn, params, locals_, transfers, count, depth + 1
            )
        deps |= arg_deps
        if writes or star_write or inner_calls:
            # The literal's body sequences AT this call: its stores
            # land on the captured targets' dep sets (the written
            # value's sources are captured names, the literal's
            # parameters — the call's arguments — or literal-local
            # derivations of those), and a `*p` store or an inner
            # call may reach any escaped binding or a shared queue,
            # folded like the opaque external write below.
            write_deps = deps | callee_deps
            for target in writes:
                self._store(locals_, params, target, write_deps, True)
                # `g = func(){...}` / `g = G` inside the body
                # rebinds the name — its old resolution went stale
                # with the value, so later `g()` calls resolve
                # through the fresh deps the store just folded in
                # (the opaque external callee model).
                self.func_aliases.pop(target, None)
                # The may-write leaves the name holding EITHER the
                # old literal or the fresh opaque value — keep its
                # records for the literal alternative and mark it so
                # the external model covers the rest.
                self.opaque_callees.add(target)
            if star_write or inner_calls:
                self.indirect_writes |= write_deps
                for escaped_id in self.escaped:
                    self._store(
                        locals_, params, escaped_id, write_deps, True
                    )
        if external:
            # The callee is unknown: it may write `*p = y` through a
            # pointer argument or send `y` on a channel argument —
            # fold every argument's deps AND the callee's own read
            # set (it may write through captured state too) into the
            # escaped bindings an opaque write could reach and into
            # indirect writes, like `_ALIAS_FOLD` does.
            write_deps = arg_deps | callee_deps
            self.indirect_writes |= write_deps
            for escaped_id in self.escaped:
                self._store(
                    locals_, params, escaped_id, write_deps, True
                )
        return deps

    def _field_member(self, node: Any) -> Any | None:
        """The member/binding a selector expression's FIELD names —
        the `f` in `s.f`: an imported unit's member for an `import`
        reference, else the local field record. Both a stored
        literal (`s.f = func()...`) and an opaque call (`s.f(...)`)
        key on this identity."""
        if node is None or node.type != "selector_expression":
            return None
        operand = node.child_by_field_name("operand")
        field = node.child_by_field_name("field")
        if operand is None or field is None:
            return None
        field_ref = self.references.get(self.node_key(field))
        member = (
            self.members.get(field_ref.binding_id)
            if field_ref is not None and field_ref.kind == "import"
            else self._local_field(field_ref)
        )
        if member is not None and member.name.encode(
            "utf-8"
        ) == field.text:
            return member
        return None

    def _opaque_indirect_call(
        self,
        node: Any,
        callee_node: Any,
        arguments: list[Any],
        fn: Any,
        params: dict[str, int],
        locals_: dict[str, frozenset[int]],
        transfers: list[Any],
        count: list[int],
        depth: int,
    ) -> frozenset[int]:
        """`s.f(args)` / `m[k](args)` / `mk(x)()` — an
        `indirect_or_selector` call whose callee is read through a
        field, an index, or a call result.

        Which function value the slot holds is unknowable here, so
        the call runs opaque like a func-typed parameter or a
        package `var`: the result unions the callee operand's own
        read deps, the arguments, `indirect_writes` and every
        escaped binding, and the call may write through pointer or
        channel arguments — the same write-back fold an external
        callee gets. The external effect records on the field
        member's identity for `s.f` (its `func` type pins) or on
        the container's root binding for `m[k]`; an operand that
        resolves to neither stays closed."""
        target_id: str | None = None
        nested_record_ids: set[str] | None = None
        pin_fact: Any = None
        callee_deps: frozenset[int] = frozenset()
        operand = callee_node.child_by_field_name("operand")
        operand_member_import = None
        if operand is not None and operand.type == "selector_expression":
            operand_field = operand.child_by_field_name("field")
            operand_field_ref = (
                self.references.get(self.node_key(operand_field))
                if operand_field is not None
                else None
            )
            if (
                operand_field_ref is not None
                and operand_field_ref.kind == "import"
            ):
                candidate = self.members.get(operand_field_ref.binding_id)
                if (
                    candidate is not None
                    and candidate.name.encode("utf-8")
                    == operand_field.text
                ):
                    operand_member_import = candidate
        if callee_node.type == "selector_expression":
            member = self._field_member(callee_node)
            if (
                member is not None
                and member.kind in {"var", "variable"}
                and member.type is not None
                and member.type.kind == "function"
            ):
                target_id = member.id
                pin_fact = member.type
            if operand_member_import is not None:
                # `lib.VS.F(...)` — the operand names an imported
                # member: its read is a dep-free package state-read
                # like any other imported member read.
                transfers.append(
                    CallTransfer(
                        FileSpan(
                            self.current_file,
                            operand.start_byte,
                            operand.end_byte,
                        ),
                        operand_member_import.id,
                        (),
                        frozenset(),
                        imported=True,
                    )
                )
            elif operand is not None:
                # `s.f` reads `s` — the operand's deps are the
                # callee's own read set (a `func` field itself has
                # no dep model).
                callee_deps = self.expression(
                    operand, fn, params, locals_, transfers, count,
                    depth + 1,
                )
        elif callee_node.type == "index_expression":
            index = callee_node.child_by_field_name("index")
            if operand_member_import is not None:
                # `lib.VMF[k](x)` — the container is an imported
                # member: dep-free state-read, external effect on
                # the member's identity.
                target_id = operand_member_import.id
                transfers.append(
                    CallTransfer(
                        FileSpan(
                            self.current_file,
                            operand.start_byte,
                            operand.end_byte,
                        ),
                        operand_member_import.id,
                        (),
                        frozenset(),
                        imported=True,
                    )
                )
            else:
                index_operand = operand
                while (
                    index_operand is not None
                    and index_operand.type == "parenthesized_expression"
                ):
                    index_operand = next(
                        (
                            c
                            for c in index_operand.named_children
                            if c.type != "comment"
                        ),
                        None,
                    )
                if (
                    index_operand is not None
                    and index_operand.type == "call_expression"
                ):
                    # `mk(x)[0]()` — the container is a call result:
                    # the span stands in for the anonymous slot, and
                    # the call's `chan` arguments join the external
                    # model like a `f := mk(ch)` capture (an element
                    # may hold a closure that sends on it). An
                    # `append(fs, …)` operand names the container's
                    # binding instead — the appended literal
                    # recorded under `fs`, not under the span.
                    append_cont = self._func_elem_append_target(
                        index_operand, locals_
                    )
                    target_id = (
                        append_cont
                        if append_cont is not None
                        else self._immediate_span_id(index_operand)
                    )
                    callee_deps |= self._func_result_chan_args(
                        index_operand, locals_, params
                    )
                else:
                    # `fm[k][i]()` — the operand is itself an index
                    # into a bound collection of func-element
                    # collections: elements conflate under the root
                    # `fm` binding like `fm[k]()` resolves. `fm[k]`
                    # as a nested expression eval stays closed, so
                    # the pieces evaluate separately here.
                    nested = self._func_elem_nested_operand(operand)
                    if nested is not None:
                        root_id, inner_id, inner_index = nested
                        target_id = root_id
                        callee_deps |= self.expression(
                            inner_id, fn, params, locals_,
                            transfers, count, depth + 1,
                        )
                        if (
                            inner_index is not None
                            and inner_index.type
                            not in {
                                "int_literal",
                                "rune_literal",
                                "interpreted_string_literal",
                                "raw_string_literal",
                            }
                        ):
                            callee_deps |= self.expression(
                                inner_index, fn, params, locals_,
                                transfers, count, depth + 1,
                            )
                        # The slot the call reads aliases its
                        # donors' backings (`fm := [][]func{fs}` —
                        # `fm[0][i]` aliases `fs`), so the records
                        # fold the matching donors' groups like a
                        # nested element store does.
                        nested_record_ids = (
                            {root_id}
                            | self._func_elem_groups.get(
                                root_id, set()
                            )
                        )
                        for donor_id in self._func_elem_slot_donors(
                            root_id, inner_index
                        ):
                            nested_record_ids |= {
                                donor_id
                            } | self._func_elem_groups.get(
                                donor_id, set()
                            )
                        operand = None
                    else:
                        root_ref = self._receiver_root_ref(operand)
                        if (
                            root_ref is not None
                            and root_ref.binding_id
                        ):
                            target_id = root_ref.binding_id
                if operand is not None:
                    callee_deps |= self.expression(
                        operand, fn, params, locals_, transfers,
                        count, depth + 1,
                    )
            if index is not None and index.type not in {
                "int_literal",
                "rune_literal",
                "interpreted_string_literal",
                "raw_string_literal",
            }:
                # A constant index contributes nothing — `M["id"](x)`
                # names the same slot class as `M[k](x)`. A computed
                # index evaluates like any argument.
                callee_deps |= self.expression(
                    index, fn, params, locals_, transfers, count,
                    depth + 1,
                )
        elif callee_node.type == "generic_type":
            # `fs[i](x)` — a call on an element selected by a bare-
            # identifier index parses as a generic instantiation
            # (`generic_type` + type_arguments), not an index
            # expression. The call record already classified it
            # `indirect_or_selector`; admit it only when the operand
            # names a bound func-element collection — a true
            # `F[T](x)` instantiation of a function stays closed.
            type_node = callee_node.child_by_field_name("type")
            type_args = callee_node.child_by_field_name(
                "type_arguments"
            )
            arg_exprs = (
                _children(type_args) if type_args is not None else []
            )
            resolved = (
                self._type_slot_ref_deps(type_node, locals_, params)
                if type_node is not None
                else None
            )
            bound = (
                self.bindings.get(resolved[0].binding_id)
                if resolved is not None
                else None
            )
            if (
                resolved is None
                or len(arg_exprs) != 1
                or bound is None
                or not self._func_elem_collection(bound.type)
            ):
                raise _Unsupported(
                    "unsupported_expression", _span(node)
                )
            target_id = resolved[0].binding_id
            callee_deps |= resolved[1]
            index_node = next(
                (
                    c
                    for c in arg_exprs[0].named_children
                    if c.type != "comment"
                ),
                None,
            )
            if index_node is not None and index_node.type not in {
                "int_literal",
                "rune_literal",
                "interpreted_string_literal",
                "raw_string_literal",
            }:
                resolved_index = self._type_slot_ref_deps(
                    index_node, locals_, params
                )
                if resolved_index is not None:
                    callee_deps |= resolved_index[1]
                else:
                    callee_deps |= self.expression(
                        index_node, fn, params, locals_, transfers,
                        count, depth + 1,
                    )
        elif callee_node.type == "call_expression":
            # `mk(x)()` / `lib.Mk(x)()` — the callee is the func
            # value a call returns. Go evaluates the callee
            # expression before the arguments, so the inner call's
            # own records and argument deps land first; the outer
            # call then runs opaque on the result — the inner
            # call's span stands in for the anonymous callee like
            # an immediate literal call's does. An inner call the
            # model cannot evaluate fails closed here.
            callee_deps = self.expression(
                callee_node, fn, params, locals_, transfers, count,
                depth + 1,
            )
            # The returned func value may capture a `chan` the
            # producing call received — `mk(ch)(x)` may send `x`
            # into `ch`'s queue, so its `chan` arguments join the
            # external model exactly like `f := mk(ch)` binds.
            callee_deps |= self._func_result_chan_args(
                callee_node, locals_, params
            )
            target_id = self._immediate_span_id(callee_node)
        if target_id is None:
            raise _Unsupported("unsupported_expression", _span(node))
        deps = callee_deps | self.indirect_writes
        # The callee may read caller memory through captured or
        # reached state — union every escaped binding's deps like
        # the external-callee path does.
        for escaped_id in self.escaped:
            if escaped_id in locals_:
                deps |= locals_[escaped_id]
            elif escaped_id in params:
                deps |= frozenset({params[escaped_id]})
        if nested_record_ids is not None:
            captured = frozenset().union(
                *(
                    self.closure_captures.get(t, frozenset())
                    for t in nested_record_ids
                )
            )
            # An element store folds the stored value's deps into the
            # donor's set (`fs[0] = cb` gives `fs` cb's deps) — the
            # nested call resolves that same slot, so it reads each
            # aliased backing's set too, not just the records.
            for did in nested_record_ids:
                if did == target_id:
                    continue
                if did in locals_:
                    deps |= locals_[did]
                elif did in params:
                    deps |= frozenset({params[did]})
                elif did in self._dead_local_deps:
                    deps |= self._dead_local_deps[did]
        else:
            captured = self.closure_captures.get(target_id)
        if captured is not None:
            # `s.f = func() { …x… }` stored a literal into this slot
            # — re-resolve each captured binding at the CALL site so
            # a `x = y` reseat between the store and `s.f()` reaches
            # the result (the frozen bind-time set would report the
            # old deps). Union rather than replace: the field may
            # hold another value along paths this summary cannot
            # see.
            for cbid in captured:
                root = (
                    self._chan_root(cbid)
                    if self._is_chan_binding(cbid)
                    else cbid
                )
                if root in locals_:
                    deps |= locals_[root]
                    if root in self.external_chan_locals:
                        deps |= self.indirect_writes
                elif root in params:
                    deps |= frozenset({params[root]})
                elif root in self._dead_local_deps:
                    # A captured branch-local died at the merge —
                    # the stored element still reads its last value.
                    deps |= self._dead_local_deps[root]
        if pin_fact is not None:
            self._pin_fact_identities(pin_fact)
            member_or_binding = self.members.get(
                target_id
            ) or self.bindings.get(target_id)
            if member_or_binding is not None:
                self.pinned.update(
                    member_or_binding.signature_type_ids
                )
        transfers.append(
            CallTransfer(
                FileSpan(
                    self.current_file,
                    node.start_byte,
                    node.end_byte,
                ),
                target_id,
                (),
                frozenset(),
                imported=True,
            )
        )
        arg_deps: frozenset[int] = frozenset()
        for arg in arguments:
            arg_deps |= self.expression(
                arg, fn, params, locals_, transfers, count, depth + 1
            )
        deps |= arg_deps
        # The callee may write `*p = y` or send `y` through an
        # argument — the same escaped/indirect fold every opaque
        # call does.
        # The callee may write through the state it read — like
        # the bound-literal path, the write-back carries the whole
        # call read set (`deps` already unions `arg_deps`, escaped
        # bindings, and the re-resolved captures): `fs :=
        # []func(){func(){ y = v }}; fs[0]()` writes `y` from the
        # captured `v`, so `y` must gain `v`'s deps.
        write_deps = deps | callee_deps
        self.indirect_writes |= write_deps
        for escaped_id in self.escaped:
            self._store(
                locals_, params, escaped_id, write_deps, True
            )
        # An element literal recorded under this container may
        # write a captured local (`fs := []func(){func(){ y = v }}`)
        # — the target need not be an escaped binding, so fold the
        # call's deps into each recorded write target like the
        # bound-literal call path does.
        if nested_record_ids is not None:
            nested_writes = frozenset().union(
                *(
                    self.closure_writes.get(t, frozenset())
                    for t in nested_record_ids
                )
            )
        else:
            nested_writes = self.closure_writes.get(target_id, ())
        for target in nested_writes:
            self._store(
                locals_, params, target, write_deps, True
            )
            self.func_aliases.pop(target, None)
            self.opaque_callees.add(target)
        return deps

    def _interface_dispatch_call(
        self,
        node: Any,
        call: Any,
        arguments: list[Any],
        fn: Any,
        params: dict[str, int],
        locals_: dict[str, frozenset[int]],
        transfers: list[CallTransfer],
        count: list[int],
        depth: int,
    ) -> frozenset[int]:
        """`I.M(recv, args)` — a method-expression call on an
        interface-typed receiver.

        Dispatch is dynamic: which implementation runs is
        unknowable here, so the call runs opaque like a func-typed
        parameter or a package `var` call — the result unions the
        receiver's read deps, the arguments, `indirect_writes` and
        every escaped binding, and the callee may write through
        pointer arguments or send on channel arguments. Every
        `chan` argument joins the external model — the unknown
        implementation may hand it back or send on it — and the
        external effect records on the receiver's root binding
        (the value the dynamic implementation is reached through).
        A named interface's identity (`call.target`) pins so a
        method-set redeclare stales the caller; a receiver that
        names no root binding stays closed. A `method`-flagged
        record (`i.M(args)`) never reaches here — an interface-typed
        operand is always an unsupported binding, so the unit only
        emits `method_expr` dispatches."""
        receiver_node = None
        if call.method:
            raise _Unsupported(
                "call_mapping_unavailable",
                _span(node),
                call.target,
            )
        if call.method_expr and arguments:
            # `I.M(recv, args)` — the receiver is already the
            # leading argument, evaluated below like every argument.
            receiver_node = arguments[0]
        receiver_deps: frozenset[int] = frozenset()
        arg_deps: frozenset[int] = frozenset()
        for arg in arguments:
            arg_deps |= self.expression(
                arg, fn, params, locals_, transfers, count, depth + 1
            )
        deps = receiver_deps | arg_deps | self.indirect_writes
        for escaped_id in self.escaped:
            if escaped_id in locals_:
                deps |= locals_[escaped_id]
            elif escaped_id in params:
                deps |= frozenset({params[escaped_id]})
        # `i.M(q)` — the dynamic implementation may send on or
        # hand back a channel argument, so every `chan` argument
        # joins the external model and its queue contents may
        # reach the result.
        deps |= self._promote_chan_call_args(
            node, "", locals_, params
        )
        target_id = call.target
        if receiver_node is not None:
            root_ref = self._receiver_root_ref(receiver_node)
            if (
                root_ref is not None
                and root_ref.binding_id
            ):
                target_id = root_ref.binding_id
        if not target_id:
            raise _Unsupported(
                "unresolved_or_opaque_call", _span(node)
            )
        if call.target:
            self.pinned.add(call.target)
        # `I[N].M(...)` — the named/alias identities the receiver's
        # type arguments resolve to pin exactly like an instantiated
        # callee's: `I` alone does not cover a redeclare of `N`.
        self.pinned.update(getattr(call, "type_arg_type_ids", ()))
        transfers.append(
            CallTransfer(
                FileSpan(
                    self.current_file,
                    node.start_byte,
                    node.end_byte,
                ),
                target_id,
                (),
                frozenset(),
                imported=True,
            )
        )
        # The callee may write `*p = y` or send `y` through an
        # argument — the same escaped/indirect fold every opaque
        # call does.
        write_deps = arg_deps | receiver_deps
        self.indirect_writes |= write_deps
        for escaped_id in self.escaped:
            self._store(
                locals_, params, escaped_id, write_deps, True
            )
        return deps

    def _bound_method_call(
        self,
        node: Any,
        arguments: list[Any],
        bound_mv: tuple[str, str | None, str | None],
        fn: Function,
        params: dict[str, int],
        locals_: dict[str, frozenset[int]],
        transfers: list[CallTransfer],
        count: list[int],
        depth: int,
        frozen_recv: frozenset[int] | None = None,
    ) -> frozenset[int]:
        """`f(args)` where `f := s.M` / `f := St.M` bound a method.

        The call resolves through the method's summary like
        `s.M(args)`: the receiver was COPIED into the value at bind
        time, so `frozen_recv` — its dep set snapshotted by
        `_record_bound_method` — sits at actuals[0], matching the
        receiver-as-parameter-0 convention. A `s = …` reseat
        between bind and call does NOT shift what `f` calls. A
        method-*expression* record (`f := St.M`) carries no receiver
        binding — argument 0 IS the receiver, exactly like the
        direct `St.M(st, args)` call.
        """
        method_id, recv_id, operand_type_id = bound_mv
        target = self.functions.get(method_id)
        if (
            target is None
            or target.receiver is None
            or target.generic
            or target.variadic
        ):
            raise _Unsupported("unsupported_expression", _span(node))
        method_expr = recv_id is None
        expected = (
            len(target.parameters) + (1 if method_expr else 0)
        )
        if len(arguments) != expected:
            raise _Unsupported(
                "callee_unavailable", _span(node), method_id
            )
        arg_args = arguments[1:] if method_expr else arguments
        if method_expr:
            recv_deps = self.expression(
                arguments[0], fn, params, locals_,
                transfers, count, depth + 1,
            )
            recv_binding = None
            elem_type_id = target.receiver.type.type_id
            if target.receiver.type.kind == "pointer":
                # `f := P.M; f(p, v)` — the callee reads and writes
                # `*recv`, pointee memory outside the pointer's own
                # dep set, so union the broadcast writes like
                # `p.V()`'s auto-deref does.
                recv_deps |= self.indirect_writes
                elem = self._pointee_type(elem_type_id)
                if elem is not None:
                    elem_type_id = elem.type.type_id
            if (
                operand_type_id is not None
                and elem_type_id is not None
                and operand_type_id != elem_type_id
            ):
                # Promoted method expression — `f := Outer.Get`
                # where the callee's receiver is `Outer`'s embedded
                # `*Inner`: reads and writes reach the embeddee's
                # pointee, not `outer`'s own fields. Union the
                # broadcast write set so `f(outer)` sees updates
                # made through `outer.Inner` after the struct was
                # built.
                recv_deps |= self.indirect_writes
            if target.receiver.type.kind != "pointer":
                root_ref = self._receiver_root_ref(arguments[0])
                if (
                    root_ref is not None
                    and (rb := self.bindings.get(
                        root_ref.binding_id
                    )) is not None
                    and rb.type.kind == "pointer"
                ):
                    # `f(p, x)` on a value receiver auto-derefs —
                    # union pointee deps like `St.M(p, x)` does.
                    recv_deps |= self.indirect_writes
        else:
            recv_binding = self.bindings.get(recv_id)
            if frozen_recv is not None:
                recv_deps = frozen_recv
            elif recv_id in locals_:
                recv_deps = locals_[recv_id]
            elif recv_id in params:
                recv_deps = frozenset({params[recv_id]})
            else:
                raise _Unsupported(
                    "unsupported_expression", _span(node)
                )
            if (
                recv_binding is not None
                and recv_binding.type.kind == "pointer"
                and target.receiver.type.kind != "pointer"
            ):
                # `p.V()` on a value receiver auto-derefs — the callee
                # reads pointee memory, which broadcasts through
                # `indirect_writes`, not `p`'s own set.
                recv_deps |= self.indirect_writes
        actual = (
            recv_deps,
            *(
                self.expression(
                    arg, fn, params, locals_,
                    transfers, count, depth + 1,
                )
                for arg in arg_args
            ),
        )
        callee = self.summarize(method_id)
        if not callee.available:
            reason = (
                "recursive_call_graph"
                if any(
                    g.reason == "recursive_call_graph"
                    for g in callee.gaps
                )
                else "callee_unsupported"
            )
            raise _Unsupported(reason, _span(node), method_id)
        assert callee.return_dependencies is not None
        result = frozenset(
            i
            for parameter in callee.return_dependencies
            for i in actual[parameter]
        )
        if operand_type_id is not None:
            # A method expression's method-set lookup names the
            # OPERAND type (`f := Outer.Get` resolves through
            # `Outer`'s set — possibly promoted from an embedded
            # field), which the callee's `*Inner` receiver does not
            # pin. Dependents of `Outer` must still flag this
            # summary when that set changes.
            self.pinned.add(operand_type_id)
        for p in (
            *((target.receiver,) if target.receiver is not None else ()),
            *target.parameters,
            *target.results,
        ):
            if p.type.type_id:
                self.pinned.add(p.type.type_id)
                named = self._pointee_type(p.type.type_id)
                if (
                    named is not None
                    and named.type.kind == "pointer"
                ):
                    self._pin_fact_identities(named.type)
        transfers.append(
            CallTransfer(
                FileSpan(
                    self.current_file,
                    node.start_byte,
                    node.end_byte,
                ),
                method_id,
                actual,
                result,
                imported=callee.effects == "unknown",
            )
        )
        if callee.effects == "unknown":
            stored = (
                frozenset().union(*actual) if actual else frozenset()
            )
            self._store_call_writes(
                list(arguments), stored, locals_, params
            )
            if target.receiver.type.kind == "pointer":
                # `f := s.M` on a `*T` method captures `&s` — the
                # callee's writes land in the receiver binding like
                # `st.M()`'s auto-ref fold. A pointer receiver
                # binding (`f := p.M`) writes through the pointer —
                # broadcast like `*p = v`.
                if method_expr:
                    # `f := P.M; f(arg0, …)` on a `*T` method — the
                    # receiver is argument 0 and Go only admits a
                    # pointer-typed (or promoted-through-pointer)
                    # operand there, so the callee's writes always
                    # land in pointee memory: an explicit pointer
                    # (`f(p, v)`), a field argument (`f(box.P, v)`),
                    # or a promoted receiver (`f := Outer.M` where
                    # `Outer` embeds `*Inner` and the write goes
                    # through `outer.Inner`, NOT `outer`'s fields —
                    # folding onto the argument's binding would lose
                    # it). Broadcast like `*p = v`.
                    self.indirect_writes |= stored
                    for escaped_id in self.escaped:
                        if escaped_id in locals_:
                            locals_[escaped_id] |= stored
                        elif escaped_id in params:
                            locals_[escaped_id] = (
                                frozenset({params[escaped_id]})
                                | stored
                            )
                elif (
                    recv_binding is not None
                    and recv_binding.type.kind == "pointer"
                ):
                    self.indirect_writes |= stored
                    for escaped_id in self.escaped:
                        if escaped_id in locals_:
                            locals_[escaped_id] |= stored
                        elif escaped_id in params:
                            locals_[escaped_id] = (
                                frozenset({params[escaped_id]})
                                | stored
                            )
                else:
                    # `&s` was captured at bind time but the binding
                    # is the same variable — fold onto its CURRENT
                    # deps, not the frozen receiver snapshot.
                    base = (
                        locals_[recv_id]
                        if recv_id in locals_
                        else (
                            frozenset({params[recv_id]})
                            if recv_id in params
                            else recv_deps
                        )
                    )
                    locals_[recv_id] = base | stored
            elif (
                recv_binding is not None
                and recv_binding.type.kind == "chan"
            ):
                # `f := c.Send` on a named `chan` type — the callee's
                # `c <- x` lands in the queue the caller shares.
                # A parameter or callee-produced channel broadcasts
                # like `G(ch)`'s sends; a `make(chan)` local folds
                # into the binding's queue deps.
                if (
                    recv_id in params
                    or recv_id in self.external_chan_locals
                ):
                    self.indirect_writes |= stored
                locals_[recv_id] = (
                    locals_.get(recv_id)
                    or recv_deps
                ) | stored
            if self._calls_touch_external_chan(callee.calls):
                self.indirect_writes |= stored
                if self._calls_touch_external_chan(
                    callee.calls, self._chan_chan_id
                ):
                    # `m.cc <- q` inside the method — the same
                    # promotion the direct-call site applies.
                    self._promote_chan_arg_roots(
                        arguments, "", locals_, params
                    )
        return result

    def _immediate_literal_call(
        self,
        node: Any,
        literal: Any,
        arguments: list[Any],
        fn: Any,
        params: dict[str, int],
        locals_: dict[str, frozenset[int]],
        transfers: list[Any],
        count: list[int],
        depth: int,
    ) -> frozenset[int]:
        """`func(...) T { ... }(args)` — a literal invoked in place.

        The callee is this very literal, so the call models like a
        bound-literal `h()` whose captures are the literal's own
        free variables resolved right here: the result unions their
        CURRENT dep sets, the arguments, and `indirect_writes` (a
        captured pointer may read caller memory the capture cannot
        name). A literal that captures a pointer unions the escaped
        bindings and records an imported transfer on the captured
        pointer, and one capturing a parameter or external channel
        may receive on it inside — the same receive-side effect a
        bound literal records. The literal's own gate still applies:
        an internal send, go or defer stays closed, while a store or
        call admits as an opaque effectful body — its write deps fold
        into each write target (and into escaped memory plus
        `indirect_writes` for a `*p` store or inner call) right here,
        where the literal runs."""
        # Go evaluates the arguments before the body, so captures and
        # alias resolution read the state AFTER `G(&x, y)`-shaped
        # arguments land — an arg that stores through `&x` or reseats
        # a channel alias changes what the literal's free names mean.
        arg_deps: frozenset[int] = frozenset()
        for arg in arguments:
            arg_deps |= self.expression(
                arg, fn, params, locals_, transfers, count, depth + 1
            )
        (
            deps,
            captured,
            captures_pointer,
            writes,
            star_write,
            has_call,
        ) = self._func_literal_capture(literal, params, locals_)
        deps |= self.indirect_writes | arg_deps
        pointer_capture = next(
            (
                cbid
                for cbid in captured
                if (
                    (binding := self.bindings.get(cbid)) is not None
                    and binding.type.kind == "pointer"
                )
            ),
            None,
        )
        # `<-ch` inside the literal (a unary receive, or a range over
        # the channel) may pull from an external queue — one captured
        # by name, or one passed in as an argument
        # (`func(ch) { <-ch }(q)`). A channel operand only carries the
        # effect when the body actually RECEIVES on it: `func(ch)
        # { return x }(q)` never touches the queue, so recording the
        # op would mark the summary `unknown` and fold phantom
        # write-throughs into the caller's deps.
        lit_param_ids: list[str | None] = []
        lit_variadic = False
        plist = literal.child_by_field_name("parameters")
        if plist is not None:
            for decl in plist.named_children:
                if decl.type not in {
                    "parameter_declaration",
                    "variadic_parameter_declaration",
                }:
                    continue
                if decl.type == "variadic_parameter_declaration":
                    lit_variadic = True
                for c in decl.named_children:
                    if c.type == "identifier":
                        pb = self.bindings_by_span.get(self.node_key(c))
                        lit_param_ids.append(
                            pb.id if pb is not None else None
                        )
        # `c := ch` inside the literal aliases the queue under an
        # internal name — a receive on the alias reaches the root, so
        # map each simple `name := identifier`/`name = identifier`
        # before scanning receives.
        lit_chan_alias: dict[str, str] = {}
        recv_bids: set[str] = set()
        # The DFS below pops children in reverse order, so a use
        # could scan before its declaration — collect the simple
        # `name := identifier`/`name = identifier` aliases in a
        # separate pass first.
        alias_stack = [literal]
        while alias_stack:
            cur = alias_stack.pop()
            alias_stack.extend(_children(cur))
            if cur.type in {
                "short_var_declaration",
                "var_declaration",
            }:
                left = cur.child_by_field_name("left")
                right = cur.child_by_field_name("right")
                lefts = _children(left) if left is not None else []
                rights = _children(right) if right is not None else []
                if (
                    len(lefts) == len(rights) == 1
                    and lefts[0].type == "identifier"
                    and rights[0].type == "identifier"
                ):
                    lb = self.bindings_by_span.get(
                        self.node_key(lefts[0])
                    )
                    rr = self.references.get(
                        self.node_key(rights[0])
                    )
                    if lb is not None and rr is not None:
                        lit_chan_alias[lb.id] = rr.binding_id

        def _recv_base_bid(opnd: Any) -> str | None:
            # `<-(ch)` / `range (ch)` unwrap like every operand read;
            # `<-qs[0]` on a `...chan` parameter receives through the
            # variadic slice's element, whose base is the param.
            while (
                opnd is not None
                and opnd.type == "parenthesized_expression"
            ):
                opnd = next(
                    (
                        c
                        for c in opnd.named_children
                        if c.type != "comment"
                    ),
                    None,
                )
            if opnd is None:
                return None
            if opnd.type == "index_expression":
                return _recv_base_bid(
                    opnd.child_by_field_name("operand")
                )
            if opnd.type == "identifier":
                rr = self.references.get(self.node_key(opnd))
                if rr is not None:
                    bid = rr.binding_id
                    seen: set[str] = set()
                    while bid in lit_chan_alias and bid not in seen:
                        seen.add(bid)
                        bid = lit_chan_alias[bid]
                    return bid
            return None

        stack = [literal]
        while stack:
            cur = stack.pop()
            operand = None
            is_range = False
            if cur.type == "unary_expression":
                op = cur.child_by_field_name("operator")
                if op is not None and op.type == "<-":
                    operand = cur.child_by_field_name("operand")
            elif cur.type == "range_clause":
                operand = cur.child_by_field_name("right")
                is_range = True
            if operand is not None:
                # `range qs` over a `...chan` slice yields its
                # elements without receiving — only `range qs[i]` (a
                # channel element) or `range ch` (a channel binding)
                # pulls. A bare `<-x` operand is a channel by type.
                norm = operand
                while (
                    norm is not None
                    and norm.type == "parenthesized_expression"
                ):
                    norm = next(
                        (
                            c
                            for c in norm.named_children
                            if c.type != "comment"
                        ),
                        None,
                    )
                rbid = _recv_base_bid(operand)
                if rbid is not None and (
                    not is_range
                    or (norm is not None and norm.type == "index_expression")
                    or self._scalar_chan_binding(rbid)
                ):
                    recv_bids.add(rbid)
            stack.extend(_children(cur))
        external_chans: set[str] = set()
        for cbid in captured:
            if self._scalar_chan_binding(cbid) and cbid in recv_bids:
                root = self._chan_root(cbid)
                if (
                    root in params
                    or root in self.external_chan_locals
                ):
                    external_chans.add(root)
        for i, arg in enumerate(arguments):
            if i < len(lit_param_ids):
                param_bid = lit_param_ids[i]
            elif lit_variadic and lit_param_ids:
                # Every argument at and past the last declared
                # position lands in the variadic slice — `func(qs
                # ...chan){<-qs[0]}(q1, q2)` receives through ANY of
                # them.
                param_bid = lit_param_ids[-1]
            else:
                param_bid = None
            if param_bid is None or param_bid not in recv_bids:
                continue
            cb = self._chan_binding(arg, locals_, params)
            root = cb.id if cb is not None else None
            if root is not None and (
                root in params or root in self.external_chan_locals
            ):
                external_chans.add(root)
                continue
            ext = self._external_chan_operand(arg, params)
            if ext is not None:
                external_chans.add(ext[0])
                continue
            # `func(ch) { <-ch }(Id(q))` — the argument is a
            # callee-produced queue, external like a `ch := g()`
            # binding is: record the receive against the callee's
            # identity.
            target = self._chan_result_call(arg)
            if target is not None:
                external_chans.add(target.binding_id)
        if captures_pointer:
            for escaped_id in self.escaped:
                if escaped_id in locals_:
                    deps |= locals_[escaped_id]
                elif escaped_id in params:
                    deps |= frozenset({params[escaped_id]})
        for target in (
            ([pointer_capture] if captures_pointer else [])
            + sorted(external_chans)
            + (
                # An effectful literal body (`x = y`, `*p = y`, an
                # inner call) records the imported transfer on the
                # call's own span identity when no captured pointer
                # or channel names it.
                [self._immediate_span_id(node)]
                if (writes or star_write or has_call)
                and not captures_pointer
                and not external_chans
                else []
            )
        ):
            transfers.append(
                CallTransfer(
                    FileSpan(
                        self.current_file,
                        node.start_byte,
                        node.end_byte,
                    ),
                    target,
                    (),
                    frozenset(),
                    imported=True,
                )
            )
        if writes or star_write or has_call:
            # The literal's body runs in place: its stores land on
            # the captured targets' dep sets now, and a `*p` store or
            # an inner call folds like an opaque callee's write.
            write_deps = deps
            for target in writes:
                self._store(locals_, params, target, write_deps, True)
                # Same stale-resolution drop as the bound-literal
                # call: `g = func(){...}` in place rebinds `g`.
                self.func_aliases.pop(target, None)
                # The may-write leaves the name holding EITHER the
                # old literal or the fresh opaque value — keep its
                # records for the literal alternative and mark it so
                # the external model covers the rest.
                self.opaque_callees.add(target)
            if star_write or has_call:
                self.indirect_writes |= write_deps
                for escaped_id in self.escaped:
                    self._store(
                        locals_, params, escaped_id, write_deps, True
                    )
        return deps

    def _immediate_span_id(self, node: Any) -> str:
        """Transfer identity for an immediate literal call whose
        effect has no captured pointer/channel to name — the call's
        own span stands in for the anonymous callee."""
        return f"{self.current_file}:{node.start_byte}:{node.end_byte}"

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
        declared = self._declared_call_summary(call, receiver, actual)
        if declared is not None:
            # The manifest covers this callee: fold its declared
            # `return_dependencies` through the actual arguments
            # instead of the opaque every-argument union. `imported`
            # follows the callee's declared effects exactly like a
            # local callee's own transfers — a bounded callee leaves
            # the caller's `effects` bounded too.
            result = (
                frozenset().union(
                    *(actual[i] for i in declared.return_dependencies)
                )
                if declared.return_dependencies
                else frozenset()
            ) | receiver_deps
            transfers.append(
                CallTransfer(
                    call.span,
                    call.target,
                    actual,
                    result,
                    imported=declared.effects == "unknown",
                    folded_targets=self._declared_transitive_targets(
                        declared
                    ),
                )
            )
            if declared.effects == "unknown":
                # An effectful declared callee may store through an
                # `&x` argument — the same conservative union a local
                # callee with unknown effects applies.
                stored = (
                    frozenset().union(*actual)
                    if actual
                    else frozenset()
                )
                self._store_call_writes(
                    arguments, stored, locals_, params
                )
                # The declared callee's recorded ops on an external
                # channel share its queue with the caller — same
                # broadcast the local-callee site applies.
                if self._calls_touch_external_chan(declared.calls):
                    self.indirect_writes |= stored
                    if self._calls_touch_external_chan(
                        declared.calls, self._chan_chan_id
                    ):
                        # `cc <- q` inside the declared callee —
                        # the same argument-root promotion.
                        self._promote_chan_arg_roots(
                            arguments, "", locals_, params
                        )
            # The callee's declared type pins fold like a local
            # call's — redeclaring any of them flags this summary.
            self.pinned.update(declared.pinned)
            # The callee's declared statement reads need no fold:
            # every one maps through actual arguments to a subset of
            # the deps the call-site statement already records by
            # evaluating those arguments.
            member = self.members.get(call.target)
            if member is not None:
                self.pinned.update(member.signature_type_ids)
            self.pinned.update(getattr(call, "type_arg_type_ids", ()))
            self._modeled_spans.add(_key3(call.span))
            return result
        self._opaque_spans.add(_key3(call.span))
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

    def _declared_call_summary(
        self, call: Any, receiver: Any, actual: tuple
    ) -> "FunctionSummary | None":
        """The declared callee summary an imported call may fold.

        Only a plain `lib.F(args)` call folds: a method or method-
        expression carries a receiver the manifest's parameter
        ordinals do not describe. The entry must be `available` —
        a gapped or bodyless declared summary widens nothing — and
        declare exactly the call's arity; otherwise the call keeps
        today's opaque every-argument approximation.
        """
        if (
            not self.declared
            or receiver is not None
            or getattr(call, "method", False)
            or getattr(call, "method_expr", False)
        ):
            return None
        key = _declared_key(call.target)
        if key is None:
            return None
        summary = self.declared.get(key)
        if summary is None:
            return None
        self._declared_seen.add(summary.binding_id)
        if (
            not summary.available
            or summary.return_dependencies is None
            or len(summary.parameters) != len(actual)
            or len(actual) > 0
            and max(summary.return_dependencies, default=-1) >= len(actual)
        ):
            return None
        return summary

    def _declared_transitive_targets(
        self, summary: "FunctionSummary"
    ) -> tuple[str, ...]:
        """Callee identities a folded summary's declared deps ride on.

        The fold embeds the callee's declared result through the actual
        arguments, so this summary's staleness now covers whatever the
        callee's own `call_targets` reached — the manifest's declared
        entries followed transitively, plus any outside it (the
        callee's own imports stay valid anchors: the declared input
        asserted them). Keeping the chain in `call_targets` lets
        `stale_dependents` flag this summary when a transitive dep
        churns even though the directly named callee's own bytes did
        not change.
        """
        seen = set()
        stack = list(summary.call_targets)
        while stack:
            target = stack.pop()
            if target in seen:
                continue
            seen.add(target)
            key = _declared_key(target)
            if key is not None:
                nxt = self.declared.get(key)
                if nxt is not None:
                    stack.extend(nxt.call_targets)
        seen.discard(summary.binding_id)
        return tuple(sorted(seen))

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
            # `G((ch))` names the same queue as `G(ch)` — unwrap
            # parens before the shape checks below.
            while (
                arg_node is not None
                and arg_node.type == "parenthesized_expression"
            ):
                arg_node = next(
                    (
                        c
                        for c in arg_node.named_children
                        if c.type != "comment"
                    ),
                    None,
                )
            if arg_node is None:
                continue
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
                    arg_binding = self.bindings.get(ref.binding_id)
                    if (
                        arg_binding is not None
                        and arg_binding.type.kind == "pointer"
                    ):
                        # `G(&p)` — the callee's `*q` IS p itself:
                        # a `*q = r` store reseats the pointer, so
                        # its provenance gains the write's deps.
                        self._ptr_deps[ref.binding_id] = (
                            self._pointer_deps(
                                ref.binding_id, params, locals_
                            )
                            | stored
                        )
            elif arg_node.type == "identifier":
                # `G(p)` hands the callee a pointer binding — the
                # callee's `*q` stores write caller memory, so every
                # argument's dependencies fold into the indirect-write
                # set (a later `*p` read observes them) and into each
                # escaped binding (`p := &x` may have aimed at any of
                # them) — the same approximation a `*p = v` store
                # uses.
                ref = self.references.get(self.node_key(arg_node))
                binding = (
                    self.bindings.get(ref.binding_id)
                    if ref is not None
                    else None
                )
                if binding is not None and binding.type.kind == "pointer":
                    self.indirect_writes |= stored
                    for escaped_id in self.escaped:
                        self._store(
                            locals_, params, escaped_id, stored, True
                        )
                        eb = self.bindings.get(escaped_id)
                        if (
                            eb is not None
                            and eb.type.kind == "pointer"
                        ):
                            # A callee `*q = r` store may reseat an
                            # escaped pointer — its provenance gains
                            # the stored deps like a caller-side
                            # `p = q` does.
                            self._ptr_deps[escaped_id] = (
                                self._pointer_deps(
                                    escaped_id, params, locals_
                                )
                                | stored
                            )
                elif (
                    binding is not None
                    and binding.type.kind == "chan"
                ):
                    # `G(ch)` hands the callee a shared queue — its
                    # sends land in it like a caller-side `ch <- x`:
                    # a local channel's conflated set gains the deps;
                    # a channel parameter's live in external state,
                    # so they broadcast into `indirect_writes` where
                    # a later `<-ch` observes them. `G(alias)` names
                    # the root queue the alias stands for — storing
                    # on the alias's own slot would hide the send
                    # from `<-ch`.
                    chan_id = self._chan_root(binding.id)
                    if chan_id in params or (
                        chan_id in self.external_chan_locals
                    ):
                        self.indirect_writes |= stored
                    elif chan_id in locals_:
                        locals_[chan_id] = (
                            locals_.get(chan_id, frozenset())
                            | stored
                        )
                elif (
                    binding is not None
                    and binding.type.kind == "struct"
                ):
                    # `G(s)` hands the callee a struct whose
                    # pointer/chan/map/slice fields share caller
                    # memory — `*s.P = x`, `s.C <- x`, `s.M[k] = v`
                    # writes reach shared state the caller can
                    # observe through `*q`/`&s.V` escapes and later
                    # calls, so they broadcast into `indirect_writes`
                    # like a pointer argument's do. The struct's own
                    # field VALUES stay by-value — the callee cannot
                    # reseat `s` or its fields — so `locals_[s]`
                    # correctly keeps its pre-call set.
                    self.indirect_writes |= stored


def _declared_key(binding_id: str) -> tuple[str, int] | None:
    """A binding identity reduced to the unit-shape-invariant parts.

    Binding ids serialize `sha256:<file digest>:<decl start>:<scope>`
    for a single-file unit and `sha256:<file digest>:<file index>:<decl
    start>:<scope>` for a package unit — the same declaration mints a
    different string under each shape, and imported call targets always
    carry the package shape. (File digest, decl start) is injective for
    function summaries: two declarations in one file never share a byte
    offset, and identical file bytes mint identical digests.
    """
    parts = binding_id.split(":")
    if len(parts) not in (5, 6) or parts[0] != "sha256":
        return None
    try:
        return parts[1], int(parts[2] if len(parts) == 5 else parts[3])
    except ValueError:
        return None


def _declared_map(
    declared: "GoSummarySet | None",
) -> dict[tuple[str, int], FunctionSummary] | None:
    if declared is None:
        return None
    result: dict[tuple[str, int], FunctionSummary] = {}
    ambiguous: set[tuple[str, int]] = set()
    for entry in declared.functions:
        key = _declared_key(entry.binding_id)
        if key is None or key in result or key in ambiguous:
            # Two manifest entries resolving to one declaration position
            # describe the same callee under contradictory declared
            # data — monotone widening: neither may fold.
            ambiguous.add(key)
            result.pop(key, None)
            continue
        result[key] = entry
    return result


def _call_modeling(
    builder: "_Builder", declared: "GoSummarySet | None"
) -> dict | None:
    """The advisory `--summary-aware-calls` counts, or None without a
    declared callee manifest."""
    if declared is None:
        return None
    return {
        "summary_modeled_calls": len(builder._modeled_spans),
        "opaque_calls": len(builder._opaque_spans),
        "summary_unmatched": len(
            [
                f
                for f in declared.functions
                if f.binding_id not in builder._declared_seen
            ]
        ),
    }


def summarize_go(
    source: str,
    snapshot: GoTypeSnapshot,
    declared: "GoSummarySet | None" = None,
) -> GoSummarySet:
    """Compose conservative dependencies only; never infer equality or safety.

    A nonempty set can overapproximate dependence (e.g. x*0 still includes x).
    Empty means parameter-independent in this fragment, not a known constant.
    None means unavailable, never a parameter-independent or effect-free result.

    `declared` (`--summary-aware-calls`) is a declared callee manifest:
    a `direct_import` call whose target binding identity it covers folds
    the declared `return_dependencies`/`statement_reads` instead of the
    opaque every-argument approximation — trusted as declared; a callee
    the manifest misses keeps opaque behavior, so a partial manifest can
    never narrow below today's width.
    """
    raw, key = _context(source, snapshot)
    key = _declared_context_key(key, declared)
    builder = _Builder(
        {0: raw},
        snapshot,
        key,
        lambda bid: snapshot.cfg_for_function(source, bid),
        declared=_declared_map(declared),
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
    return GoSummarySet(
        key,
        results,
        snapshot.target_arch,
        call_modeling=_call_modeling(builder, declared),
    )


def summarize_go_package(
    sources: "dict[str, str] | list[str]",
    snapshot: GoPackageSnapshot,
    declared: "GoSummarySet | None" = None,
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
    key = _declared_context_key(key, declared)
    builder = _Builder(
        dict(enumerate(raws)),
        snapshot,
        key,
        lambda bid: snapshot.cfg_for_function(sources, bid),
        declared=_declared_map(declared),
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
    return GoSummarySet(
        key,
        results,
        snapshot.target_arch,
        call_modeling=_call_modeling(builder, declared),
    )
