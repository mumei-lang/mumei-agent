"""C06 Rust scalar interprocedural summaries (declared route family).

The C06 scalar interprocedural summary model on a single Rust
source file: scalar params (`i*`/`u*`/`f*`/`bool`/`char`),
`let` declarations, if/else joins, a one-pass loop
may-analysis, intra-file function calls, and return/tail-
expression dependency tracking. Everything outside the
fragment stays closed (gap recorded). With a `resolver` (or
`--resolve-modules` on the produce route), `mod NAME;` declarations
resolve through it and `use` bindings alias names into the resolved
modules — unresolvable declarations and paths stay opaque, the same
over-approximation as no resolver.

- `summarize_rust(source)` → `RustSummarySet` with
  `context_key`, `functions`, and `profile`.
"""

from __future__ import annotations

import contextlib
import hashlib
from dataclasses import dataclass, field

PROFILE = "mumei.rust-scalar-parameter-deps/v1"
MAX_NODES = 20000
MAX_FUNCTIONS = 256
MAX_INLINE_DEPTH = 48
MAX_SOURCE_BYTES = 64 * 1024
MAX_MODULE_DEPTH = 8

_SCALAR = (
    lambda t: t.startswith(("i8", "i16", "i32", "i64", "i128",
                           "u8", "u16", "u32", "u64", "u128",
                           "f32", "f64", "usize", "isize"))
    or t in {"bool", "char"}
)


# Declared-manifest restoration bounds and validators — the same
# fail-closed shape `GoSummarySet.from_dict` enforces: a manifest is
# declared data, so unknown keys, wrong types and oversize
# collections are malformed, never partially adopted.
MAX_MANIFEST_MEMBERS = 8192


def _require_manifest(condition: bool) -> None:
    if not condition:
        raise ValueError("declared summary manifest is malformed")


def _manifest_record(
    value, required: tuple[str, ...], optional: tuple[str, ...] = ()
) -> dict:
    if not isinstance(value, dict) or not (
        set(required) <= set(value) <= set(required) | set(optional)
    ):
        raise ValueError("declared summary manifest is malformed")
    return value


def _string(value) -> str:
    if type(value) is not str:
        raise ValueError("declared summary manifest is malformed")
    return value


def _boolean(value) -> bool:
    if type(value) is not bool:
        raise ValueError("declared summary manifest is malformed")
    return value


def _list(value) -> list:
    if type(value) is not list:
        raise ValueError("declared summary manifest is malformed")
    return value


def _deps_from_list(value) -> frozenset[int]:
    deps = _list(value)
    _require_manifest(
        len(deps) <= MAX_MANIFEST_MEMBERS
        and all(type(d) is int and d >= 0 for d in deps)
    )
    return frozenset(deps)


@dataclass(frozen=True)
class RustGap:
    reason: str
    byte: int

    def to_dict(self) -> dict:
        return {"reason": self.reason, "byte": self.byte}

    @classmethod
    def from_dict(cls, value) -> "RustGap":
        v = _manifest_record(value, ("reason", "byte"))
        _require_manifest(type(v["byte"]) is int and v["byte"] >= 0)
        return cls(_string(v["reason"]), v["byte"])


@dataclass(frozen=True)
class RustCall:
    byte: int
    name: str | None
    actual: tuple
    returns: frozenset | None

    def to_dict(self) -> dict:
        return {
            "byte": self.byte,
            "name": self.name,
            "arguments": [sorted(a) for a in self.actual],
            "result": (
                None if self.returns is None else sorted(self.returns)
            ),
        }

    @classmethod
    def from_dict(cls, value) -> "RustCall":
        v = _manifest_record(
            value, ("byte", "name", "arguments", "result")
        )
        _require_manifest(type(v["byte"]) is int and v["byte"] >= 0)
        _require_manifest(v["name"] is None or type(v["name"]) is str)
        arguments = _list(v["arguments"])
        _require_manifest(len(arguments) <= MAX_MANIFEST_MEMBERS)
        result = v["result"]
        return cls(
            v["byte"],
            v["name"],
            tuple(_deps_from_list(a) for a in arguments),
            None if result is None else _deps_from_list(result),
        )


@dataclass(frozen=True)
class RustStatementRead:
    """Parameter ordinals read while evaluating one statement.

    `span` is the statement node's `(start_byte, end_byte)` —
    stable within the file that produced it and meaningless
    across modules, so manifests only compare spans inside a
    single summary set."""

    span: tuple
    deps: frozenset

    def to_dict(self) -> dict:
        return {
            "span": [self.span[0], self.span[1]],
            "deps": sorted(self.deps),
        }

    @classmethod
    def from_dict(cls, value) -> "RustStatementRead":
        v = _manifest_record(value, ("span", "deps"))
        span = _list(v["span"])
        _require_manifest(
            len(span) == 2
            and all(type(b) is int and b >= 0 for b in span)
        )
        return cls(
            (span[0], span[1]), _deps_from_list(v["deps"])
        )


@dataclass
class RustFunctionSummary:
    name: str
    params: tuple
    available: bool
    return_dependencies: frozenset | None
    calls: list = field(default_factory=list)
    gaps: list = field(default_factory=list)
    effects: str = "none_in_supported_fragment"
    statement_reads: tuple = ()

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "available": self.available,
            "parameters": list(self.params),
            "return_dependencies": (
                None
                if self.return_dependencies is None
                else sorted(self.return_dependencies)
            ),
            "calls": [c.to_dict() for c in self.calls],
            "gaps": [g.to_dict() for g in self.gaps],
            "effects": self.effects,
            "statement_reads": [
                r.to_dict() for r in self.statement_reads
            ],
        }

    @classmethod
    def from_dict(cls, value) -> "RustFunctionSummary":
        v = _manifest_record(
            value,
            (
                "name",
                "available",
                "parameters",
                "return_dependencies",
                "calls",
                "gaps",
                "effects",
            ),
            ("statement_reads",),
        )
        parameters = _list(v["parameters"])
        calls = _list(v["calls"])
        gaps = _list(v["gaps"])
        _require_manifest(
            len(parameters) <= MAX_MANIFEST_MEMBERS
            and len(calls) <= MAX_MANIFEST_MEMBERS
            and len(gaps) <= MAX_MANIFEST_MEMBERS
        )
        deps = v["return_dependencies"]
        restored_deps = None if deps is None else _deps_from_list(deps)
        restored_gaps = [RustGap.from_dict(g) for g in gaps]
        statement_reads = [
            RustStatementRead.from_dict(r)
            for r in _list(v.get("statement_reads", []))
        ]
        _require_manifest(len(statement_reads) <= MAX_MANIFEST_MEMBERS)
        available = _boolean(v["available"])
        # A manifest may not contradict itself: `available` tracks
        # exactly "a result was derived and no gap was recorded" —
        # a forged flag cannot borrow trust the record lacks.
        _require_manifest(
            available == (restored_deps is not None)
            and available == (not restored_gaps)
        )
        # An ordinal outside the declared parameter range can never
        # come from an honest derivation — the record is malformed
        # rather than merely unmatchable.
        _require_manifest(
            restored_deps is None
            or max(restored_deps, default=-1) < len(parameters)
        )
        return cls(
            _string(v["name"]),
            tuple(_string(p) for p in parameters),
            available,
            restored_deps,
            [RustCall.from_dict(c) for c in calls],
            restored_gaps,
            _string(v["effects"]),
            tuple(statement_reads),
        )


@dataclass
class RustSummarySet:
    context_key: str
    profile: str
    functions: list
    # `--summary-aware-calls` reporting: present only on manifests
    # derived with a declared callee manifest — advisory counts
    # (`summary_modeled_calls` folded, `opaque_calls` left opaque,
    # `summary_unmatched` manifest entries never referenced), never
    # a verdict or a gate.
    call_modeling: dict | None = None

    def to_dict(self) -> dict:
        doc = {
            "schema_version": self.profile,
            "context_key": self.context_key,
            "functions": [f.to_dict() for f in self.functions],
        }
        if self.call_modeling is not None:
            doc["call_modeling"] = self.call_modeling
        return doc

    @classmethod
    def from_dict(cls, value) -> "RustSummarySet":
        """Restore a declared manifest — strict, bounded, fail-closed.

        The manifest is declared data, not trusted input: unknown or
        missing keys, wrong types and oversize collections are all
        malformed — the caller fails closed rather than adopting a
        partial set."""
        v = _manifest_record(
            value,
            ("schema_version", "context_key", "functions"),
            ("call_modeling",),
        )
        _require_manifest(v["schema_version"] == PROFILE)
        functions = _list(v["functions"])
        _require_manifest(len(functions) <= MAX_MANIFEST_MEMBERS)
        call_modeling = v.get("call_modeling")
        _require_manifest(
            call_modeling is None or type(call_modeling) is dict
        )
        restored = [
            RustFunctionSummary.from_dict(f) for f in functions
        ]
        names = [f.name for f in restored]
        # A declared duplicate name would let a forged record adopt a
        # same-named honest record's reuse — names are unique in every
        # honest derivation, so a duplicate is malformed.
        _require_manifest(len(set(names)) == len(names))
        return cls(
            _string(v["context_key"]),
            PROFILE,
            restored,
            call_modeling=call_modeling,
        )


class _Unsupported(Exception):
    def __init__(self, reason, byte):
        super().__init__(reason)
        self.reason = reason
        self.byte = byte


def _children(node):
    return [c for c in node.children if c.is_named]


def _type_name(tnode):
    """Innermost named type under reference/mut wrappers —
    `p: &mut P` yields `P`. `None` for unnameable types."""
    if tnode is None:
        return None
    if tnode.type in ("type_identifier", "primitive_type"):
        return tnode.text.decode()
    named = [
        d
        for d in _descendants(tnode)
        if d.type in ("type_identifier", "primitive_type")
    ]
    return named[-1].text.decode() if named else None


def _is_mut_ref(node):
    """A `&mut x` argument — a slot an opaque callee may write."""
    return node is not None and node.type == "reference_expression" and any(
        c.type == "mutable_specifier" for c in _children(node)
    )


def _is_mut_ref_type(tnode):
    """A `&mut T` parameter type — a slot the callee may write through."""
    return (
        tnode is not None
        and tnode.type == "reference_type"
        and any(c.type == "mutable_specifier" for c in _children(tnode))
    )


def _ref_inner(node):
    """`&e`/`&mut e` → the inner expression node; else None."""
    if node is None or node.type != "reference_expression":
        return None
    return next(
        (
            c
            for c in _children(node)
            if c.type not in _TYPE_NAMES
            and c.type != "mutable_specifier"
        ),
        None,
    )


def _unparen(node):
    """`(e)` — parentheses are transparent: unwrap to the inner
    expression so `(p)`/`&mut (p)`/`&mut (*p)` behave exactly like
    their unwrapped forms."""
    while node is not None and node.type == "parenthesized_expression":
        kids = [c for c in _children(node)]
        node = kids[0] if len(kids) == 1 else None
    return node


def _arg_root(node):
    """Innermost identifier under reference/member/index
    wrappers — the slot a `&mut` argument writes through."""
    while node is not None:
        if node.type in {"identifier", "self"}:
            return node.text.decode()
        if node.type == "field_expression":
            node = node.child_by_field_name("value")
            continue
        if node.type == "index_expression":
            node = next(
                (
                    c for c in _children(node)
                    if c.type != "type_cast_expression"
                ),
                None,
            )
            continue
        kids = [
            c for c in _children(node)
            if c.type not in _TYPE_NAMES
        ]
        if len(kids) == 1:
            node = kids[0]
            continue
        return None
    return None


def _pattern_bindings(pat):
    """Identifier names bound by a pattern, skipping every
    `type` subtree (`Some(v)` binds `v`, not `Some`)."""
    if pat is None:
        return []
    if pat.type == "identifier":
        return [pat.text.decode()]
    out = []

    def walk(n):
        t = n.child_by_field_name("type")
        for c in _children(n):
            if c is t:
                continue
            if c.type == "identifier":
                out.append(c.text.decode())
                continue
            walk(c)

    walk(pat)
    return out


def _descendants(node):
    out = []

    def walk(n):
        for c in n.children:
            if not c.is_named:
                continue
            out.append(c)
            walk(c)

    walk(node)
    return out


def _span(node):
    return node.start_byte


def _scalar_type(tnode):
    if tnode is None:
        return False
    if tnode.type == "primitive_type":
        return _SCALAR(tnode.text.decode())
    return False


class _Builder:
    def __init__(
        self,
        source: bytes,
        resolver=None,
        resolving=frozenset(),
        module_cache=None,
        module_digests=None,
        source_path=None,
        resolved_paths=None,
        declared=None,
    ):
        self.source = source
        self.count = [0]
        self.functions: dict[str, object] = {}
        self.summaries: dict[str, RustFunctionSummary] = {}
        self._inline_depth = 0
        self._writes: list = []
        self._decls: list = []
        # Per-statement read attribution: `_statement` pushes one
        # frame per in-flight statement; `_expr` unions every
        # evaluated dep set into every open frame, so a statement's
        # reads cover its nested expressions and any inlined
        # callee bodies (keyed by the callee's own spans).
        self._read_stack: list = []
        self._stmt_reads: dict = {}
        self.methods: dict = {}
        # `const K` / `static S` — compile-time constant, so a
        # read is dep-free; `static mut` writes mark unknown.
        self.globals: set = set()
        self.mut_globals: set = set()
        self._in_progress: set = set()
        self._type_envs: list = []
        self._mut_ref_params: list = []
        self._block_decls: list = []
        # Optional module resolver — the same contract as the TS
        # builder: maps a `mod NAME;` declaration's specifier to
        # source text (bytes/str) or a resolved Path; None is both
        # "no resolver" and "unresolvable" (names stay opaque).
        self.resolver = resolver
        # Ancestor (importer_path, spec) declaration keys — the
        # cycle guard; `module_cache` shares resolved-module bytes
        # across the unit; `module_digests` feeds `context_key`.
        self.resolving = set(resolving)
        # Ancestor resolved-byte digests — a pathless resolver
        # that feeds a module its own source would otherwise
        # synthesize a fresh importer identity each level and
        # defeat the `resolving` key check.
        self.resolving_bytes: set = set()
        self.module_cache = (
            module_cache if module_cache is not None else {}
        )
        self.module_digests = (
            module_digests if module_digests is not None else {}
        )
        # Out-param: the filesystem paths of every resolved
        # module — routes refuse `--output` targets that would
        # overwrite one.
        self.resolved_paths = resolved_paths
        self.source_path = source_path
        # `--summary-aware-calls`: the declared callee manifest's
        # name -> entry map; `_declared_seen` feeds
        # `summary_unmatched`.
        self._declared_set = declared
        self._declared = (
            {f.name: f for f in declared.functions}
            if declared is not None
            else {}
        )
        self._declared_seen: set = set()
        self._modeled_calls = 0
        self._opaque_calls = 0
        if resolver is not None:
            import inspect

            try:
                self._resolver_importer = (
                    len(inspect.signature(resolver).parameters) > 1
                )
            except (TypeError, ValueError):
                self._resolver_importer = False
        else:
            self._resolver_importer = False
        # Registry key -> (use_map, mod_path) of the module that
        # declared it; `_summarize` installs them as the current
        # scope so call sites resolve `use` bindings and
        # module-relative names.
        self.mod_scopes: dict = {}
        self._cur_use_map: dict = {}
        self._cur_mod_path = ""
        # Per-scope `name -> deps` of outer bindings captured at the
        # point a `let` first shadows them: assignments before the
        # shadow reach the outer binding, so block exit restores this
        # value — not the block-entry snapshot.
        self._shadow_vals: list = []

    # -- unit scan -------------------------------------------------

    def _parse(self, source):
        from tree_sitter import Language, Parser
        import tree_sitter_rust

        parser = Parser(Language(tree_sitter_rust.language()))
        return parser.parse(source).root_node

    def build(self) -> RustSummarySet:
        root = self._parse(self.source)
        self._scan_module(
            _children(root), "", {}, "", self.source_path
        )
        if len(self.functions) > MAX_FUNCTIONS:
            raise _Unsupported("analysis_limit", 0)
        summaries = []
        for name, fn_node in self.functions.items():
            try:
                # A callee already summarized inline for an
                # earlier caller is reused — re-walking it would
                # double-count its calls in the `call_modeling`
                # advisory.
                cached = self.summaries.get(name)
                summaries.append(
                    cached
                    if cached is not None
                    else self._summarize(name, fn_node)
                )
            except (_Unsupported, RecursionError) as u:
                if isinstance(u, _Unsupported):
                    gap = RustGap(u.reason, u.byte)
                else:
                    gap = RustGap("analysis_limit", _span(fn_node))
                partial = getattr(u, "partial_summary", None)
                if partial is None:
                    partial = RustFunctionSummary(
                        name=name, params=(), available=False,
                        return_dependencies=None,
                        gaps=[],
                        effects="unknown",
                    )
                # A failed walk can't characterize its effects —
                # stay fail-closed.
                partial.effects = "unknown"
                partial.gaps.append(gap)
                summaries.append(partial)
        if self.resolved_paths is not None:
            self.resolved_paths.update(
                entry[1]
                for entry in self.module_cache.values()
                if entry and entry[1]
            )
        # The context key folds every resolved module's bytes with
        # the root source — a changed module invalidates reuse.
        # Under `--summary-aware-calls` the callee manifest's
        # canonical bytes fold in too — it is a derivation input
        # like the sources, so a changed manifest invalidates the
        # strict whole-context gate.
        ctx = hashlib.sha256(self.source)
        for ref, digest in sorted(self.module_digests.items()):
            ctx.update(ref.encode())
            ctx.update(b"\x00")
            ctx.update(digest.encode())
            ctx.update(b"\x00")
        if self._declared_set is not None:
            import json

            ctx.update(
                json.dumps(
                    self._declared_set.to_dict(), sort_keys=True
                ).encode()
            )
        return RustSummarySet(
            context_key=ctx.hexdigest(),
            profile=PROFILE,
            functions=summaries,
            call_modeling=self._call_modeling(),
        )

    def _declared_entry(self, cname):
        """Declared manifest entry for an opaque call's recorded name.

        The recorded name normalizes `::` to `.` and drops leading
        `crate.`/`self.`/`super.` roots; a name that stays qualified
        also matches one module-token prefix over the callee's
        standalone name (`b::T::f` -> `T.f`), never a deeper strip.
        """
        if not self._declared or cname is None:
            return None
        norm = cname.replace("::", ".")
        for root in ("crate.", "self.", "super."):
            if norm.startswith(root):
                norm = norm[len(root):]
                break
        entry = self._declared.get(norm)
        if entry is None and "." in norm:
            entry = self._declared.get(norm.split(".", 1)[1])
        if entry is not None:
            self._declared_seen.add(entry.name)
        return entry

    def _call_modeling(self):
        """The `call_modeling` advisory block — only on manifests
        derived with a declared callee manifest."""
        if self._declared_set is None:
            return None
        return {
            "summary_modeled_calls": self._modeled_calls,
            "opaque_calls": self._opaque_calls,
            "summary_unmatched": (
                len(self._declared) - len(self._declared_seen)
            ),
        }

    # -- module scan ----------------------------------------------

    def _scan_module(
        self, items, prefix, use_map, mod_path, importer_path
    ):
        """One module's top-level scan — the root file, an inline
        `mod` body, or a resolved `mod NAME;` file. `prefix` is the
        registry-key prefix (`"b."`); `mod_path` the dotted module
        path (`"b.c"`) used for `self`/`super` and same-module
        resolution. `use_map` collects this module's `use`
        bindings; every registered function records `(use_map,
        mod_path)` in `mod_scopes`. `methods` registers every
        module's impls — dispatch filters candidates to the
        caller's scope. `globals`/`mut_globals` register under the
        module's `prefix`; read/write sites resolve ancestor-first
        so sibling scopes stay invisible."""
        for top in items:
            if top.type == "use_declaration":
                self._scan_use(top, use_map, mod_path)
                continue
            if top.type == "function_item":
                name = top.child_by_field_name("name")
                if name is None:
                    continue
                base = name.text.decode()
                ukey = f"{prefix}{base}"
                n = 1
                while ukey in self.functions:
                    n += 1
                    ukey = f"{prefix}{base}#{n}"
                self.functions[ukey] = top
                self.mod_scopes[ukey] = (use_map, mod_path)
                continue
            if top.type == "mod_item":
                decls = top.child_by_field_name("body")
                mname = top.child_by_field_name("name")
                if mname is None:
                    continue
                mtext = mname.text.decode()
                child_path = (
                    f"{mod_path}.{mtext}" if mod_path else mtext
                )
                if decls is not None:
                    self._scan_module(
                        _children(decls),
                        f"{prefix}{mtext}.",
                        {},
                        child_path,
                        self._child_importer(
                            importer_path, mtext
                        ),
                    )
                elif not _has_path_attr(top):
                    # `#[path = "..."]` locates the module file
                    # outside the resolver contract — the
                    # declaration stays opaque rather than
                    # resolving the wrong bytes.
                    self._resolve_mod(
                        mtext,
                        f"{prefix}{mtext}.",
                        child_path,
                        importer_path,
                    )
                continue
            if top.type in {"const_item", "static_item"}:
                gname = top.child_by_field_name("name")
                if gname is not None:
                    gtext = gname.text.decode()
                    self.globals.add(f"{prefix}{gtext}")
                    if any(
                        c.type == "mutable_specifier"
                        for c in top.children
                    ):
                        self.mut_globals.add(
                            f"{prefix}{gtext}"
                        )
                continue
            if top.type != "impl_item":
                continue
            decls = top.child_by_field_name("body")
            typ = top.child_by_field_name("type")
            if decls is None or typ is None:
                continue
            tname = typ.text.decode()
            for item in _children(decls):
                if item.type != "function_item":
                    continue
                name = item.child_by_field_name("name")
                if name is None:
                    continue
                base = name.text.decode()
                ukey = f"{prefix}{tname}.{base}"
                n = 1
                while ukey in self.functions:
                    n += 1
                    ukey = f"{prefix}{tname}.{base}#{n}"
                self.functions[ukey] = item
                self.mod_scopes[ukey] = (use_map, mod_path)
                self.methods.setdefault(base, set()).add(ukey)

    def _child_importer(self, importer_path, mname):
        """Synthetic importer for an inline `mod` body: `mod b
        { mod c; }` in `a.rs` resolves `c` beneath `a/b/`. A
        suffix-less path makes `_fs_resolver` treat it as a stem
        directory."""
        if importer_path is None:
            return None
        return str(_mod_base(importer_path) / mname)

    def _resolve_mod(self, mname, prefix, mod_path, importer_path):
        """`mod b;` without a body — resolve through the module
        resolver and scan the file under the `b.` prefix.
        Unresolvable, oversized or cyclic declarations contribute
        nothing: the names stay opaque, the same
        over-approximation as no resolver."""
        if self.resolver is None:
            return
        rkey = (
            str(importer_path) if importer_path else "", mname
        )
        # The ancestor check comes BEFORE the cache lookup — a
        # degenerate resolver returning the same bytes for the
        # same declaration would otherwise hit its own cache
        # entry and recurse `a.a.a...` forever.
        if rkey in self.resolving:
            return
        # `module_ref` feeds both the digest key (fresh
        # resolutions) and the pathless child's importer identity
        # (cache hits) — compute it before either branch.
        module_ref = (
            f"{importer_path}\x00{mname}"
            if importer_path is not None
            else mname
        )
        if rkey in self.module_cache:
            child = self.module_cache[rkey]
        else:
            child = None
            if len(self.resolving) < MAX_MODULE_DEPTH:
                raw = (
                    self.resolver(mname, importer_path)
                    if self._resolver_importer
                    else self.resolver(mname)
                )
                child_path = None
                from pathlib import Path as _P

                if isinstance(raw, _P):
                    child_path = str(raw)
                    module_ref = child_path
                    try:
                        raw = raw.read_bytes()
                    except OSError:
                        raw = None
                if isinstance(raw, str):
                    raw = raw.encode()
                if (
                    isinstance(raw, bytes)
                    and len(raw) <= MAX_SOURCE_BYTES
                ):
                    self.module_digests[module_ref] = (
                        hashlib.sha256(raw).hexdigest()
                    )
                    child = (raw, child_path)
            self.module_cache[rkey] = child
        if child is None:
            return
        raw, child_path = child
        if (
            child_path is None
            and hashlib.sha256(raw).hexdigest()
            in self.resolving_bytes
        ):
            # Pathless resolution can't name the module file, so a
            # resolver feeding a module its own bytes recurses
            # under a fresh synthetic importer every level — byte
            # identity is the only cycle witness there. Distinct
            # `Path` resolutions with equal content are different
            # files, not a cycle.
            return
        self.resolving.add(rkey)
        # A pathless (bytes/str) resolution still needs a unique
        # importer identity for its own `mod` declarations —
        # `None` would collide every pathless parent's same-named
        # `mod` in `module_cache` and the digest key.
        importer_for_child = (
            child_path if child_path is not None else module_ref
        )
        if child_path is None:
            self.resolving_bytes.add(
                hashlib.sha256(raw).hexdigest()
            )
        try:
            self._scan_module(
                _children(self._parse(raw)),
                prefix,
                {},
                mod_path,
                importer_for_child,
            )
        finally:
            self.resolving.discard(rkey)
            if child_path is None:
                self.resolving_bytes.discard(
                    hashlib.sha256(raw).hexdigest()
                )

    # -- `use` bindings and path resolution ------------------------

    def _scan_use(self, decl, use_map, mod_path):
        """`use` bindings for this module's scope: local name ->
        normalized registry key. `use` paths are
        crate-root-relative unless `self`/`super`/`crate`
        prefixed; globs bind nothing (`use b::*` stays opaque)."""
        self._use_tree(
            decl.child_by_field_name("argument"),
            [],
            use_map,
            mod_path,
        )

    def _use_tree(self, node, prefix, use_map, mod_path):
        if node is None:
            return
        t = node.type
        if t == "use_wildcard":
            return
        if t == "use_as_clause":
            path = node.child_by_field_name("path")
            alias = node.child_by_field_name("alias")
            if path is not None and alias is not None:
                segs = prefix + self._scoped_segments(path)
                use_map[alias.text.decode()] = self._norm_key(
                    segs, mod_path
                )
            return
        if t == "scoped_use_list":
            path = node.child_by_field_name("path")
            lst = node.child_by_field_name("list")
            base = prefix + (
                self._scoped_segments(path)
                if path is not None
                else []
            )
            if lst is not None:
                for c in _children(lst):
                    self._use_tree(c, base, use_map, mod_path)
            return
        if t == "use_list":
            for c in _children(node):
                self._use_tree(c, prefix, use_map, mod_path)
            return
        if t == "scoped_identifier":
            segs = prefix + self._scoped_segments(node)
        elif t in {"identifier", "crate", "self", "super"}:
            segs = prefix + [node.text.decode()]
        else:
            return
        name = segs[-1]
        if name == "self" and prefix:
            # `use a::b::{self}` binds `b` itself.
            name = prefix[-1]
        use_map[name] = self._norm_key(segs, mod_path)

    def _norm_key(self, segs, mod_path):
        key = self._path_key(segs, mod_path)
        return key if key is not None else ".".join(segs)

    def _scoped_segments(self, node):
        """`b::c::f` / `crate::b::f` -> `[b, c, f]` — walks the
        nested `path`/`name` chain down to the leaf."""
        segs = []
        cur = node
        while cur is not None and cur.type == "scoped_identifier":
            name = cur.child_by_field_name("name")
            path = cur.child_by_field_name("path")
            if name is None:
                break
            segs.insert(0, name.text.decode())
            cur = path
        if cur is not None:
            segs.insert(0, cur.text.decode())
        return segs

    def _path_key(self, segs, mod_path):
        """Normalize a `crate`/`self`/`super`-headed path to a
        registry key; None for an ordinary head (relative
        resolution is `_resolve_scoped`'s job)."""
        if not segs:
            return None
        head, rest = segs[0], segs[1:]
        tail = ".".join(rest)
        if head == "crate":
            return tail
        if head == "self":
            return (
                f"{mod_path}.{tail}" if mod_path else tail
            )
        if head == "super":
            parent = (
                mod_path.rsplit(".", 1)[0]
                if "." in mod_path
                else ""
            )
            return f"{parent}.{tail}" if parent else tail
        return None

    def _resolve_ident(self, name, locals_):
        """Bare call name -> registry key. A local binding
        shadows file/module items (None -> opaque); then `use`
        bindings; then a same-module item (`b::f` called as `f`
        inside `mod b`); then the crate root."""
        if name in locals_:
            return None
        bound = self._cur_use_map.get(name)
        if bound is not None:
            return bound if bound in self.functions else None
        if self._cur_mod_path:
            cand = f"{self._cur_mod_path}.{name}"
            if cand in self.functions:
                return cand
        return name if name in self.functions else None

    def _resolve_scoped(self, path, nm):
        """`b::c::f` / `crate::b::f` / `self::f` / `super::f`
        -> registry key. Candidates, in order: `use`-bound head
        segment, `crate`/`self`/`super`-normalized, same-module
        prefixed, then the crate-root join."""
        segs = self._scoped_segments(path)
        segs.append(nm.text.decode())
        if not segs:
            return None
        cands = []
        bound = self._cur_use_map.get(segs[0])
        if bound is not None:
            # A `use` binding is authoritative: `use std::fs`
            # makes `fs::read` mean `std::fs::read` and nothing
            # else — falling through to a same-named internal
            # item would mis-resolve an external path.
            cand = ".".join([bound] + segs[1:])
            return cand if cand in self.functions else None
        key = self._path_key(segs, self._cur_mod_path)
        if key is not None:
            cands.append(key)
        if self._cur_mod_path:
            cands.append(
                f"{self._cur_mod_path}.{'.'.join(segs)}"
            )
        cands.append(".".join(segs))
        for cand in cands:
            if cand in self.functions:
                return cand
        return None

    def _global_of(self, name, table):
        """Bare `NAME` resolves module-local `const`/`static`
        first, then ancestors', then the crate root's — sibling
        scopes stay invisible. A `use` binding is authoritative:
        `use b::STATE` makes `STATE` mean `b.STATE` and nothing
        else."""
        bound = self._cur_use_map.get(name)
        if bound is not None:
            return bound if bound in table else None
        mp = self._cur_mod_path
        while mp:
            key = f"{mp}.{name}"
            if key in table:
                return key
            mp = mp.rpartition(".")[0]
        return name if name in table else None

    def _is_local_name(self, name, param_index):
        """A parameter or a `let`-bound name — writes to it stay
        local. A `use`-imported static's writes also land in
        `locals_` (dependency tracking), so slot membership alone
        cannot tell a shadowing local from the static."""
        return name in param_index or any(
            name in decls for decls in self._block_decls
        )

    # -- per-function summary --------------------------------------

    def _summarize(self, name, fn_node) -> RustFunctionSummary:
        # `T.m` / `T.m#n` — the impl type `self` binds to.
        stem = name.split("#", 1)[0]
        self_type = stem.rsplit(".", 1)[0] if "." in stem else None
        prev_scope = (self._cur_use_map, self._cur_mod_path)
        self._cur_use_map, self._cur_mod_path = (
            self.mod_scopes.get(name, ({}, ""))
        )
        self._in_progress.add(name)
        self._writes.append(set())
        self._decls.append(set())
        self._mut_ref_params.append(set())
        types: dict = {}
        self._type_envs.append(types)
        # `_block_decls` is a stack of per-block `let`-name sets —
        # a callee inlined mid-body must not see the caller's `let`
        # names, or its write to a `use`-imported static would look
        # like a write to the caller's local.
        prev_block_decls = self._block_decls
        prev_reads = self._stmt_reads
        prev_stack = self._read_stack
        self._block_decls = [set()]
        self._read_stack = []
        self._stmt_reads = {}
        # Read records are per-function: a callee summarized
        # through `_call` collects its own `statement_reads` —
        # the caller's frames never see the callee body's spans,
        # only the actuals' deps at the call site.
        summary = None
        try:
            params = fn_node.child_by_field_name("parameters")
            param_names = []
            locals_: dict = {}
            param_index: dict = {}
            if params is not None:
                idx = 0
                for p in _children(params):
                    if p.type == "self_parameter":
                        param_names.append("self")
                        param_index["self"] = idx
                        locals_["self"] = frozenset({idx})
                        if self_type is not None:
                            types["self"] = self_type
                        if (
                            p.text.decode()
                            .replace(" ", "")
                            .startswith("&mut")
                        ):
                            self._mut_ref_params[-1].add("self")
                        idx += 1
                        continue
                    if p.type not in ("parameter", "variadic_parameter"):
                        continue
                    pat = p.child_by_field_name("pattern")
                    ptype = _type_name(p.child_by_field_name("type"))
                    if pat is not None and pat.type == "identifier":
                        # Any identifier param — scalar or not —
                        # gets a dep index (over-approx: reads carry
                        # the param's dep).
                        pname = pat.text.decode()
                        param_names.append(pname)
                        param_index[pname] = idx
                        locals_[pname] = frozenset({idx})
                        if ptype is not None:
                            types[pname] = ptype
                        if _is_mut_ref_type(
                            p.child_by_field_name("type")
                        ):
                            self._mut_ref_params[-1].add(pname)
                    elif pat is not None:
                        # Destructured `(a, b)` / `S { x }` patterns —
                        # bind each identifier inside to the dep index.
                        bound = [
                            d for d in _descendants(pat)
                            if d.type == "identifier"
                        ]
                        if bound:
                            for d in bound:
                                locals_[d.text.decode()] = frozenset(
                                    {idx}
                                )
                                # A destructured parameter is a
                                # function-scope local like a `let`.
                                self._block_decls[0].add(
                                    d.text.decode()
                                )
                        param_names.append(pat.text.decode())
                    else:
                        param_names.append("_")
                    # Wildcards (`_`), pattern-less and unbound
                    # patterns still consume a parameter slot —
                    # `params` keeps a placeholder name so a dep
                    # index stays aligned with the entry at that
                    # position.
                    idx += 1
            # `params` is fixed before the body walk — a
            # partial summary carried on `_Unsupported` keeps
            # the names its dep indexes refer to.
            summary = RustFunctionSummary(
                name=name, params=tuple(param_names),
                available=False,
                return_dependencies=None,
            )
            body = fn_node.child_by_field_name("body")
            ret = (
                self._block(body, locals_, param_index, summary)
                if body is not None
                else None
            )
            ret_mark = getattr(summary, "return_mark", None)
            if (
                ret is None
                and ret_mark is None
                and fn_node.child_by_field_name("return_type") is not None
            ):
                raise _Unsupported("missing_return", _span(fn_node))
            ret = (ret or frozenset()) | (ret_mark or frozenset())
            summary.return_dependencies = ret
            summary.available = True
            return summary
        except (_Unsupported, RecursionError) as exc:
            # Carry the partially built summary so `build` can
            # keep the reads recorded before the failure. The
            # dep indexes on `partial_deps` name THIS function's
            # parameters — its own reads already landed in its
            # `statement_reads`, so a caller composing this
            # summary through `_call` must not inherit them.
            exc.partial_deps = frozenset()
            if summary is not None:
                exc.partial_summary = summary
            raise
        finally:
            self._type_envs.pop()
            self._mut_ref_params.pop()
            self._writes.pop()
            self._decls.pop()
            self._in_progress.discard(name)
            self._cur_use_map, self._cur_mod_path = prev_scope
            self._block_decls = prev_block_decls
            # Reads recorded up to the point of failure still
            # attach — a gapped walk's partial attribution stays
            # truthful about what was read before the gap.
            if summary is not None:
                summary.statement_reads = tuple(
                    RustStatementRead(span, deps)
                    for span, deps in sorted(
                        self._stmt_reads.items()
                    )
                )
            self._read_stack = prev_stack
            self._stmt_reads = prev_reads

    # -- statements -------------------------------------------------

    @contextlib.contextmanager
    def _scope(self, locals_, param_index):
        """A lexical scope — `let` bindings die with the block.

        `param_index`, the current type env and the `&mut`-alias set
        are only ever written by `let`, so they restore wholesale;
        `locals_` is also written by assignments to outer names, so
        only names a `let` bound inside get their old entry back —
        and a shadowed name restores the value it held at the shadow
        point, since writes before the `let` reached the outer
        binding.
        """
        self._block_decls.append(set())
        self._shadow_vals.append({})
        prev_index = dict(param_index)
        prev_types = (
            dict(self._type_envs[-1]) if self._type_envs else {}
        )
        prev_muts = (
            set(self._mut_ref_params[-1])
            if self._mut_ref_params else set()
        )
        prev_locals = dict(locals_)
        try:
            yield
        finally:
            bound = self._block_decls.pop()
            shadowed = self._shadow_vals.pop()
            param_index.clear()
            param_index.update(prev_index)
            if self._type_envs:
                self._type_envs[-1].clear()
                self._type_envs[-1].update(prev_types)
            if self._mut_ref_params:
                self._mut_ref_params[-1].clear()
                self._mut_ref_params[-1].update(prev_muts)
            for name in bound:
                if name in shadowed:
                    locals_[name] = shadowed[name]
                elif name in prev_locals:
                    locals_[name] = prev_locals[name]
                else:
                    locals_.pop(name, None)

    def _block(self, block, locals_, param_index, summary):
        ret = None
        with self._scope(locals_, param_index):
            for st in _children(block):
                self.count[0] += 1
                if self.count[0] > MAX_NODES:
                    raise _Unsupported("analysis_limit", _span(st))
                r = self._statement(st, locals_, param_index, summary)
                if r is not None:
                    ret = r if ret is None else ret | r
        # A block's trailing bare expression is its value —
        # handled inside _statement's expression arm.
        return ret

    def _record_read(self, deps) -> None:
        for i in range(len(self._read_stack)):
            self._read_stack[i] = self._read_stack[i] | deps

    def _statement(self, st, locals_, param_index, summary):
        # Every expression evaluated under this statement — its
        # own and any inlined callee body's — lands in the open
        # frames; nested statements pop their own record under
        # their own span.
        self._read_stack.append(frozenset())
        try:
            return self._statement_inner(
                st, locals_, param_index, summary
            )
        finally:
            frame = self._read_stack.pop()
            key = (st.start_byte, st.end_byte)
            self._stmt_reads[key] = self._stmt_reads.get(
                key, frozenset()
            ) | frame

    def _statement_inner(self, st, locals_, param_index, summary):
        t = st.type
        if t == "let_declaration":
            pat = st.child_by_field_name("pattern")
            val = st.child_by_field_name("value")
            if pat is None:
                return None
            deps = (
                self._expr(val, locals_, param_index, summary)
                if val is not None
                else frozenset()
            )
            bound = _pattern_bindings(pat)
            if not bound:
                raise _Unsupported(
                    "unsupported_statement", _span(st)
                )
            ltype = _type_name(st.child_by_field_name("type"))
            type_root = None
            write_root = None
            # Type inheritance and slot aliasing only make sense for
            # a plain `let q = ...` binding: a `&mut q`/`(a, b)`
            # pattern copies or destructures the value, so the bound
            # name neither carries `p`'s type nor shares `p`'s slot.
            # `let ref mut q = p` is the exception that still
            # aliases: `q` binds `&mut p`, so writes through `q`
            # reach `p`'s storage exactly like the move case.
            ref_mut_binding = (
                pat.type == "ref_pattern"
                and any(
                    c.type == "mut_pattern"
                    for c in _children(pat)
                )
            )
            if val is not None and ref_mut_binding:
                vsrc = _unparen(val)
                write_root = (
                    _arg_root(vsrc)
                    if vsrc is not None
                    else None
                )
            if val is not None and pat.type == "identifier":
                # `let q = p` / `let q = &mut p` — no annotation:
                # inherit the source binding's type so `q.m()`
                # still resolves the impl's method. A field/index
                # read (`let q = p.v`) binds the field's own type —
                # inheriting `p`'s would resolve the wrong impl, so
                # only transparent identifier/reference vals count.
                vsrc = _unparen(val)
                if vsrc is not None and vsrc.type in {
                    "identifier",
                    "self",
                }:
                    type_root = vsrc.text.decode()
                    # A moved `&mut` param: writes via `q` reach `p`.
                    write_root = type_root
                elif (
                    vsrc is not None
                    and vsrc.type == "reference_expression"
                ):
                    inner = _unparen(_ref_inner(vsrc))
                    if (
                        inner is not None
                        and inner.type in {"identifier", "self"}
                    ):
                        type_root = inner.text.decode()
                    elif _is_mut_ref(vsrc) and inner is not None:
                        # `let q = &mut *p` / `let q = &mut p.v` —
                        # writes through `q` reach `p`'s pointee.
                        write_root = _arg_root(inner)
                if (
                    type_root is not None
                    and ltype is None
                    and self._type_envs
                ):
                    ltype = self._type_envs[-1].get(type_root)
            mut_params = (
                self._mut_ref_params[-1]
                if self._mut_ref_params
                else frozenset()
            )
            for bname in bound:
                if (
                    self._block_decls
                    and bname not in self._block_decls[-1]
                    and bname in locals_
                ):
                    # First shadow of a live binding in this scope —
                    # capture the value the outer binding holds now;
                    # block exit restores it, not the block-entry
                    # snapshot.
                    self._shadow_vals[-1][bname] = locals_[bname]
                locals_[bname] = deps
                if self._writes:
                    self._writes[-1].add(bname)
                if self._decls:
                    self._decls[-1].add(bname)
                if ltype is not None and self._type_envs:
                    self._type_envs[-1][bname] = ltype
                if self._block_decls:
                    self._block_decls[-1].add(bname)
                if (
                    write_root is not None
                    and write_root in mut_params
                    and write_root in param_index
                ):
                    # `let q = p` re-binds a `&mut` parameter —
                    # writes rooted at `q` are writes through `p`.
                    param_index[bname] = param_index[write_root]
                    # `q` re-binds a `&mut`, so it is one itself:
                    # `let r = q` keeps the alias chain.
                    self._mut_ref_params[-1].add(bname)
            return None
        if t == "return_expression":
            val = next(
                (
                    c
                    for c in _children(st)
                    if c.type not in {"return"}
                ),
                None,
            )
            deps = (
                self._expr(val, locals_, param_index, summary)
                if val is not None
                else frozenset()
            )
            summary.return_mark = (
                deps
                if getattr(summary, "return_mark", None) is None
                else summary.return_mark | deps
            )
            return deps
        if t == "expression_statement":
            inner = next(
                (c for c in _children(st)), None
            )
            if inner is None:
                return None
            if inner.type in {
                "assignment_expression",
                "compound_assignment_expr",
            }:
                self._assign(inner, locals_, param_index, summary)
                return None
            if inner.type == "call_expression":
                self._call(
                    inner, locals_, param_index, summary, void=True
                )
                return None
            if (
                inner.type in _EXPR_TYPES
                and inner.type not in _STMT_EXPR_TYPES
            ):
                # A plain expression under `...;` records once —
                # on this statement's own span; a nested
                # `_statement` frame would duplicate the record
                # for every `0;`-style statement. Control-flow
                # expressions keep the `_statement` path — their
                # value-less forms return None, which `_expr`
                # cannot record.
                return self._expr(
                    inner, locals_, param_index, summary
                )
            r = self._statement(inner, locals_, param_index, summary)
            if r is not None:
                return r
            return None
        if t == "if_expression":
            return self._if(st, locals_, param_index, summary)
        if t in {
            "while_expression", "loop_expression", "for_expression",
        }:
            return self._loop(st, locals_, param_index, summary)
        if t == "match_expression":
            return self._match(st, locals_, param_index, summary)
        if t in {"block", "unsafe_block"}:
            if t == "unsafe_block":
                inner = next(
                    (c for c in _children(st)
                     if c.type == "block"),
                    None,
                )
                return (
                    self._block(
                        inner, locals_, param_index, summary
                    )
                    if inner is not None else None
                )
            return self._block(st, locals_, param_index, summary)
        if t == "break_expression":
            # `break v` — `loop { }` yields the value; under the
            # may-model the break deps join the loop's result.
            deps = frozenset()
            for c in _children(st):
                try:
                    deps |= self._expr(
                        c, locals_, param_index, summary
                    )
                except _Unsupported as exc:
                    deps |= getattr(
                        exc, "partial_deps", frozenset()
                    )
                    continue
            return deps
        if t == "continue_expression":
            return None
        if t in {
            "assignment_expression", "compound_assignment_expr",
        }:
            self._assign(st, locals_, param_index, summary)
            return None
        if t == "call_expression":
            # Bare `f(x)` in block position is the block's tail
            # value; `f(x);` is voided by expression_statement.
            return self._call(
                st, locals_, param_index, summary
            )
        # A trailing bare expression — the block's value.
        if t in _EXPR_TYPES:
            return self._expr(st, locals_, param_index, summary)
        raise _Unsupported("unsupported_statement", _span(st))

    def _if(self, st, locals_, param_index, summary):
        cond = st.child_by_field_name("condition")
        cons = st.child_by_field_name("consequence")
        alt = st.child_by_field_name("alternative")
        merged = frozenset()
        lc_pat = None
        if cond is not None:
            if cond.type == "let_condition":
                lc_val = cond.child_by_field_name("value")
                lc_pat = cond.child_by_field_name("pattern")
                if lc_val is not None:
                    merged = self._expr(
                        lc_val, locals_, param_index, summary
                    )
            else:
                merged = self._expr(
                    cond, locals_, param_index, summary
                )
        before_pw = dict(
            getattr(summary, "param_writes", None) or {}
        )
        left_locals = dict(locals_)
        if lc_pat is not None:
            # `if let Some(v) = it` — `v` binds the value's deps
            # inside the consequence scope.
            for bname in _pattern_bindings(lc_pat):
                left_locals[bname] = merged
        right_locals = dict(locals_)
        left_ret = (
            self._statement(cons, left_locals, param_index, summary)
            if cons is not None
            else None
        )
        right_ret = None
        if alt is not None:
            if alt.type == "else_clause":
                altb = next(
                    (c for c in _children(alt)), None
                )
            else:
                altb = alt
            right_ret = (
                self._statement(
                    altb, right_locals, param_index, summary
                )
                if altb is not None
                else None
            )
        for name in set(left_locals) | set(right_locals):
            locals_[name] = (
                left_locals.get(name, frozenset())
                | right_locals.get(name, frozenset())
                | merged
            )
        pw = getattr(summary, "param_writes", None)
        if pw:
            # A write inside a branch is conditioned on the
            # branch's deps — they join the recorded write.
            for key, val in pw.items():
                if val != before_pw.get(key, frozenset()):
                    pw[key] = val | merged
        ret = None
        if left_ret is not None:
            ret = left_ret
        if right_ret is not None:
            ret = right_ret if ret is None else ret | right_ret
        if ret is not None:
            ret = ret | merged
        return ret

    def _match(self, st, locals_, param_index, summary):
        scrut = st.child_by_field_name("value")
        mdeps = (
            self._expr(scrut, locals_, param_index, summary)
            if scrut is not None
            else frozenset()
        )
        arm_scopes = []
        ret = None
        for c in _children(st):
            if c.type != "match_block":
                continue
            for arm in _children(c):
                if arm.type != "match_arm":
                    continue
                scope = dict(locals_)
                aret = None
                for ac in _children(arm):
                    if ac.type == "=>":
                        continue
                    if ac.type == "match_pattern":
                        # `Some(v) => v` — `v` binds the
                        # scrutinee's deps in this arm.
                        for bname in _pattern_bindings(ac):
                            scope[bname] = mdeps
                        continue
                    aret = self._statement(
                        ac, scope, param_index, summary
                    )
                arm_scopes.append(scope)
                if aret is not None:
                    ret = aret if ret is None else ret | aret
        for name in set().union(*arm_scopes) if arm_scopes else set():
            merged = mdeps
            for sc in arm_scopes:
                merged |= sc.get(name, frozenset())
            locals_[name] = locals_.get(name, frozenset()) | merged
        if ret is not None:
            ret = ret | mdeps
        return ret

    def _loop(self, st, locals_, param_index, summary):
        cond = st.child_by_field_name("condition")
        body = st.child_by_field_name("body")
        inner = dict(locals_)
        lc_merged = frozenset()
        if (
            cond is not None
            and cond.type == "let_condition"
        ):
            # `while let Some(v) = it` — the body reads the
            # bound names, so evaluate the value first.
            lc_val = cond.child_by_field_name("value")
            lc_pat = cond.child_by_field_name("pattern")
            if lc_val is not None:
                lc_merged = self._expr(
                    lc_val, inner, param_index, summary
                )
                if lc_pat is not None:
                    for bname in _pattern_bindings(lc_pat):
                        inner[bname] = lc_merged
        if st.type == "for_expression":
            # `for i in 0..n` — bind the pattern name to the
            # iterator's deps in the loop scope.
            pat = st.child_by_field_name("pattern")
            val = st.child_by_field_name("value")
            if pat is not None and pat.type == "identifier":
                inner[pat.text.decode()] = (
                    self._expr(
                        val, inner, param_index, summary
                    )
                    if val is not None
                    else frozenset()
                )
        before_pw = dict(
            getattr(summary, "param_writes", None) or {}
        )
        self._writes.append(set())
        try:
            ret = None
            if body is not None:
                # Loop-body `let`s are scoped to the body — the
                # shared binding maps restore like a block's.
                with self._scope(inner, param_index):
                    for c in _children(body):
                        r = self._statement(
                            c, inner, param_index, summary
                        )
                        if r is not None:
                            ret = r if ret is None else ret | r
        finally:
            touched = self._writes.pop()
        merged = lc_merged
        if (
            cond is not None
            and cond.type != "let_condition"
        ):
            merged |= self._expr(
                cond, inner, param_index, summary
            )
        for name in list(locals_):
            deps = inner.get(name, frozenset())
            if deps != locals_[name] or name in touched:
                locals_[name] = locals_[name] | deps | merged
                if self._writes:
                    # An inner may-write is the parent's
                    # may-write too.
                    self._writes[-1].add(name)
        pw = getattr(summary, "param_writes", None)
        if pw:
            for key, val in pw.items():
                if val != before_pw.get(key, frozenset()):
                    pw[key] = val | merged
        if ret is not None:
            # `while s > 0 { return x; }` — whether the body ran
            # depends on the condition.
            ret = ret | merged
        return ret

    # -- assignment / call ------------------------------------------

    def _assign(self, expr, locals_, param_index, summary):
        left = expr.child_by_field_name("left")
        right = expr.child_by_field_name("right")
        if (
            left is not None
            and left.type == "identifier"
            and (
                left.text.decode() in locals_
                or self._global_of(left.text.decode(), self.mut_globals)
                is not None
            )
        ):
            deps = (
                self._expr(right, locals_, param_index, summary)
                if right is not None
                else frozenset()
            )
            name = left.text.decode()
            is_local = self._is_local_name(name, param_index)
            if expr.type == "compound_assignment_expr":
                # `x += v` reads the old slot — the LHS never
                # passes through `_expr` on the statement path,
                # so record it here.
                lhs_read = locals_.get(name, frozenset())
                deps |= lhs_read
                self._record_read(lhs_read)
            locals_[name] = deps
            if self._writes:
                self._writes[-1].add(name)
            if (
                not is_local
                and self._global_of(name, self.mut_globals)
                is not None
            ):
                # `static mut` writes are observable —
                # unknown effects. A `let`-bound local
                # shadowing a `use`-imported static stays
                # local: the write does not reach the
                # static.
                summary.effects = "unknown"
            return deps
        if left is not None and left.type in _EXPR_TYPES:
            # `*p = v`, `x.f = v`, `a[i] = v` — non-scalar
            # targets. The target path's own deps (index
            # expressions, receiver roots) join the write, and
            # the rooted slot stores the union so later reads
            # see it. When the root is a parameter (`self`,
            # `p: &mut T`) the write is also recorded so callers
            # can merge it into the slot the argument binds.
            deps = (
                self._expr(right, locals_, param_index, summary)
                if right is not None
                else frozenset()
            )
            try:
                deps |= self._expr(
                    left, locals_, param_index, summary
                )
            except _Unsupported as exc:
                deps |= getattr(
                    exc, "partial_deps", frozenset()
                )
            root = _arg_root(left)
            if root is not None:
                if root in locals_:
                    locals_[root] = locals_[root] | deps
                    if self._writes:
                        self._writes[-1].add(root)
                if root in param_index:
                    pw = getattr(
                        summary, "param_writes", None
                    )
                    if pw is None:
                        pw = {}
                        summary.param_writes = pw
                    pw[param_index[root]] = (
                        pw.get(param_index[root], frozenset())
                        | deps
                    )
                    # A write through a caller-owned reference is
                    # observable — the manifest must not read pure.
                    # `unknown` stays absorbing: an earlier global or
                    # opaque effect is not downgraded.
                    if summary.effects != "unknown":
                        summary.effects = "state_writes"
                if (
                    root not in locals_
                    and self._global_of(root, self.mut_globals)
                    is not None
                ):
                    # `static mut` writes are observable —
                    # unless a local `let` shadows the
                    # `use`-bound name.
                    summary.effects = "unknown"
            return deps
        raise _Unsupported("unsupported_statement", _span(expr))

    def _merge_mut_writes(
        self, arglist, roots, actual_union,
        locals_, param_index, summary,
    ):
        """`f(&mut x)` through an opaque callee — the pointee
        may gain any argument's deps."""
        if arglist is None:
            return
        for arg, root in zip(_children(arglist), roots):
            if root is None or not _is_mut_ref(arg):
                continue
            is_local = self._is_local_name(root, param_index)
            locals_[root] = (
                locals_.get(root, frozenset()) | actual_union
            )
            if self._writes:
                self._writes[-1].add(root)
            if (
                not is_local
                and self._global_of(root, self.mut_globals)
                is not None
            ):
                summary.effects = "unknown"
            if root in param_index:
                pw = getattr(summary, "param_writes", None)
                if pw is None:
                    pw = {}
                    summary.param_writes = pw
                pw[param_index[root]] = (
                    pw.get(param_index[root], frozenset())
                    | actual_union
                )
                if summary.effects != "unknown":
                    summary.effects = "state_writes"

    def _call(self, node, locals_, param_index, summary, void=False):
        fn_expr = node.child_by_field_name("function")
        arglist = node.child_by_field_name("arguments")
        actual = []
        roots = []
        if arglist is not None:
            for a in _children(arglist):
                actual.append(
                    self._expr(a, locals_, param_index, summary)
                )
                roots.append(_arg_root(a))
        actual_t = tuple(actual)
        actual_union = frozenset()
        for a in actual:
            actual_union |= a
        recv_deps = frozenset()
        recv = None
        fld = None
        if (
            fn_expr is not None
            and fn_expr.type == "field_expression"
        ):
            # `x.m(args)` — the receiver's deps join the opaque
            # result like another argument.
            recv = fn_expr.child_by_field_name("value")
            fld = fn_expr.child_by_field_name("field")
            if recv is not None:
                try:
                    recv_deps = self._expr(
                        recv, locals_, param_index, summary
                    )
                except _Unsupported as exc:
                    recv_deps = getattr(
                        exc, "partial_deps", frozenset()
                    )
            actual_union |= recv_deps
        name = None
        raw_ident = None
        if (
            fn_expr is not None
            and fn_expr.type == "identifier"
        ):
            # Bare name: locals shadow -> `use` bindings ->
            # same-module -> crate root.
            raw_ident = fn_expr.text.decode()
            name = self._resolve_ident(raw_ident, locals_)
        elif (
            fn_expr is not None
            and fn_expr.type == "scoped_identifier"
        ):
            # `T::f` / `b::f` / `crate::b::f` / `self::f` /
            # `super::f` — normalize the path to a registry key.
            path = fn_expr.child_by_field_name("path")
            nm = fn_expr.child_by_field_name("name")
            if path is not None and nm is not None:
                name = self._resolve_scoped(path, nm)
        elif (
            fn_expr is not None
            and fn_expr.type == "generic_function"
        ):
            # `f::<T>(args)` — same function, resolve the inner
            # callee name.
            inner_fn = fn_expr.child_by_field_name("function")
            if (
                inner_fn is not None
                and inner_fn.type == "identifier"
            ):
                raw_ident = inner_fn.text.decode()
                name = self._resolve_ident(raw_ident, locals_)
            elif (
                inner_fn is not None
                and inner_fn.type == "scoped_identifier"
            ):
                path = inner_fn.child_by_field_name("path")
                nm = inner_fn.child_by_field_name("name")
                if path is not None and nm is not None:
                    name = self._resolve_scoped(path, nm)
        elif (
            fn_expr is not None
            and fn_expr.type == "field_expression"
        ):
            # `x.m(args)` — resolve `m` when exactly one impl in
            # the file defines it; `self` binds the receiver deps
            # (param index 0).
            if fld is not None:
                ukeys = self.methods.get(
                    fld.text.decode(), set()
                )
                # Impls from other modules never answer a call in
                # this scope — `t.m()` inside `mod b` resolves
                # `b`'s impls only, so a same-named root impl is
                # never mis-picked.
                ukeys = {
                    k for k in ukeys
                    if self.mod_scopes.get(k, ({}, ""))[1]
                    == self._cur_mod_path
                }
                if len(ukeys) == 1:
                    cand = next(iter(ukeys))
                    # `T.m` — resolve `x.m()` only when the
                    # receiver's declared type is `T`; an
                    # untyped receiver stays opaque rather than
                    # borrowing another type's method.
                    req = cand.split("#", 1)[0].rsplit(".", 1)[0]
                    recv_root = (
                        _arg_root(recv)
                        if recv is not None else None
                    )
                    recv_type = (
                        self._type_envs[-1].get(recv_root)
                        if recv_root is not None and self._type_envs
                        else None
                    )
                    if recv_type is not None and recv_type.replace(
                        "::", "."
                    ) in {req, req.rsplit(".", 1)[-1]}:
                        name = cand
                        actual.insert(0, recv_deps)
                        actual_t = tuple(actual)
                        roots.insert(0, recv_root)
        if (
            name is None
            and fld is not None
            and fld.text.decode() in _CONTAINER_WRITES
        ):
            rname = _arg_root(recv) if recv is not None else None
            if rname is not None:
                slot = (
                    locals_.get(rname, frozenset())
                    | actual_union
                )
                locals_[rname] = slot
                if self._writes:
                    self._writes[-1].add(rname)
                if (
                    not self._is_local_name(rname, param_index)
                    and self._global_of(rname, self.mut_globals)
                    is not None
                ):
                    # `V.push(x)` on a `static mut` mutates
                    # external state like `V = x`.
                    summary.effects = "unknown"
                summary.calls.append(
                    RustCall(
                        _span(node),
                        f"{recv.text.decode()}."
                        f"{fld.text.decode()}",
                        actual_t, None,
                    )
                )
                return frozenset() if void else slot
        if (
            name is None
            or name not in self.functions
        ):
            # method calls, fn-pointers, enum constructors
            # (`Some(x)`), external `crate::f`, unresolved
            # module paths, and locals shadowing a file-level
            # function name — opaque record.
            bound = (
                locals_.get(raw_ident, frozenset())
                if raw_ident is not None
                else frozenset()
            )
            # `cb(...)` through a bound name reads the function
            # pointer/closure value — a voided call drops that
            # read from its result, so record it here.
            self._record_read(bound)
            result = actual_union | bound
            cname = fn_expr.text.decode() if fn_expr is not None else None
            declared_entry = (
                None
                if fld is not None
                or (
                    raw_ident is not None
                    and raw_ident in locals_
                )
                else self._declared_entry(cname)
            )
            foldable = (
                declared_entry is not None
                and not void
                and declared_entry.available
                and len(declared_entry.params) == len(actual)
                and max(
                    declared_entry.return_dependencies,
                    default=-1,
                )
                < len(actual)
            )
            if foldable:
                # `--summary-aware-calls` fold: the declared
                # return_dependencies replace the opaque
                # every-argument union. Receiver-carrying calls
                # (`x.m`, `t.f`) never fold — the manifest's
                # ordinals do not describe the receiver — and a
                # local-bound callee name stays a fn-pointer call
                # regardless of the manifest. `effects` and the
                # &mut-write merge stay opaque too: the manifest
                # cannot bound writes through argument objects.
                result = frozenset().union(
                    *(actual[i] for i in declared_entry.return_dependencies)
                ) if declared_entry.return_dependencies else frozenset()
                self._modeled_calls += 1
            elif self._declared_set is not None:
                self._opaque_calls += 1
            summary.calls.append(
                RustCall(_span(node), cname, actual_t,
                         None if void else result)
            )
            self._merge_mut_writes(
                arglist, roots, actual_union,
                locals_, param_index, summary,
            )
            summary.effects = "unknown"
            return frozenset() if void else result
        if name in self._in_progress:
            # Recursion — no fixpoint in the one-pass model;
            # record it opaquely.
            summary.calls.append(
                RustCall(_span(node), name, actual_t,
                         None if void else actual_union)
            )
            self._merge_mut_writes(
                arglist, roots, actual_union,
                locals_, param_index, summary,
            )
            summary.effects = "unknown"
            return frozenset() if void else actual_union
        callee = self.summaries.get(name)
        if callee is None:
            if self._inline_depth >= MAX_INLINE_DEPTH:
                raise _Unsupported("analysis_limit", _span(node))
            self._inline_depth += 1
            try:
                callee = self._summarize(
                    name, self.functions[name]
                )
            finally:
                self._inline_depth -= 1
            self.summaries[name] = callee
        if not callee.available or callee.return_dependencies is None:
            summary.calls.append(
                RustCall(_span(node), name, actual_t, None)
            )
            summary.effects = "unknown"
            return actual_union
        deps = frozenset()
        for i in callee.return_dependencies:
            if i < len(actual):
                deps |= actual[i]
        summary.calls.append(
            RustCall(_span(node), name, actual_t, deps)
        )
        for pidx, pdeps in getattr(
            callee, "param_writes", {}
        ).items():
            # `f(&mut p)` / `p.set(x)` — writes the callee made
            # through the parameter merge into the slot the
            # caller's argument roots at. `pdeps` live in the
            # callee's index space: dep `j` binds `actual[j]`.
            if pidx >= len(roots):
                continue
            projected = frozenset()
            for j in pdeps:
                if j < len(actual):
                    projected |= actual[j]
            rname = roots[pidx]
            if rname is None:
                summary.effects = "unknown"
                continue
            is_local = self._is_local_name(rname, param_index)
            locals_[rname] = (
                locals_.get(rname, frozenset()) | projected
            )
            if self._writes:
                self._writes[-1].add(rname)
            if (
                not is_local
                and self._global_of(rname, self.mut_globals)
                is not None
            ):
                summary.effects = "unknown"
            if rname in param_index:
                if summary.effects != "unknown":
                    summary.effects = "state_writes"
                # The callee wrote through a reference this
                # function itself received — that is this
                # function's own param write for its callers.
                pw = getattr(
                    summary, "param_writes", None
                )
                if pw is None:
                    pw = {}
                    summary.param_writes = pw
                pw[param_index[rname]] = (
                    pw.get(param_index[rname], frozenset())
                    | projected
                )
        if callee.effects == "unknown":
            summary.effects = "unknown"
        return frozenset() if void else deps

    # -- expressions -------------------------------------------------

    def _expr(self, node, locals_, param_index, summary):
        try:
            deps = self._expr_inner(node, locals_, param_index, summary)
        except _Unsupported as exc:
            # Reads evaluated before a mid-expression failure
            # still attribute to the open statement frames —
            # `_expr_inner` loops carry them on `partial_deps`.
            partial = getattr(exc, "partial_deps", None)
            if partial:
                self._record_read(partial)
            raise
        self._record_read(deps)
        return deps

    def _expr_inner(self, node, locals_, param_index, summary):
        self.count[0] += 1
        if self.count[0] > MAX_NODES:
            raise _Unsupported("analysis_limit", _span(node))
        t = node.type
        if t == "identifier" or t == "self":
            name = node.text.decode()
            if name in locals_:
                return locals_[name]
            if self._global_of(name, self.globals) is not None:
                return frozenset()
            raise _Unsupported("binding_unavailable", _span(node))
        if t in {
            "integer_literal", "float_literal", "boolean_literal",
            "char_literal", "string_literal", "negative_literal",
            "unit_expression",
        }:
            return frozenset()
        if t in {
            "binary_expression", "compound_assignment_expr",
        }:
            deps = frozenset()
            for c in _children(node):
                # `_expr_inner` recursion stays one frame per
                # level — `_expr`'s record on the way out
                # captures this subtree's union anyway.
                try:
                    deps |= self._expr_inner(
                        c, locals_, param_index, summary
                    )
                except _Unsupported as exc:
                    exc.partial_deps = (
                        getattr(exc, "partial_deps", frozenset())
                        | deps
                    )
                    raise
            return deps
        if t in {
            "unary_expression", "reference_expression",
            "try_expression", "parenthesized_expression",
            "type_cast_expression", "prefix_expression",
        }:
            deps = frozenset()
            for c in _children(node):
                if c.type in _TYPE_NAMES:
                    continue
                try:
                    deps |= self._expr_inner(
                        c, locals_, param_index, summary
                    )
                except _Unsupported as exc:
                    exc.partial_deps = (
                        getattr(exc, "partial_deps", frozenset())
                        | deps
                    )
                    raise
            return deps
        if t == "call_expression":
            return self._call(
                node, locals_, param_index, summary
            )
        if t == "assignment_expression":
            return self._assign(
                node, locals_, param_index, summary
            )
        if t == "if_expression":
            return self._if(node, locals_, param_index, summary)
        if t == "match_expression":
            return self._match(node, locals_, param_index, summary)
        if t in {
            "while_expression", "loop_expression", "for_expression",
        }:
            return self._loop(node, locals_, param_index, summary)
        if t == "block":
            return self._block(node, locals_, param_index, summary) or frozenset()
        if t == "break_expression":
            deps = frozenset()
            for c in _children(node):
                try:
                    deps |= self._expr_inner(
                        c, locals_, param_index, summary
                    )
                except _Unsupported as exc:
                    deps |= getattr(
                        exc, "partial_deps", frozenset()
                    )
                    continue
            return deps
        if t == "continue_expression":
            return frozenset()
        if t == "closure_expression":
            # `|a, b| body` — the closure value's deps are the
            # body's deps with its parameters bound to nothing;
            # captured names carry their real deps.
            cparams = node.child_by_field_name("parameters")
            cbody = node.child_by_field_name("body")
            if cbody is None:
                return frozenset()
            inner = dict(locals_)
            if cparams is not None:
                for p in _children(cparams):
                    if p.type == "parameter":
                        pp = p.child_by_field_name("pattern")
                        for bname in (
                            _pattern_bindings(pp)
                            if pp is not None else ()
                        ):
                            inner[bname] = frozenset()
                    elif p.type == "identifier":
                        inner[p.text.decode()] = frozenset()
            try:
                return self._expr_inner(
                    cbody, inner, param_index, summary
                )
            except _Unsupported as exc:
                # An unanalyzable closure body is an opaque
                # value, but reads evaluated before the failure
                # still attribute to the enclosing statement.
                self._record_read(
                    getattr(exc, "partial_deps", frozenset())
                )
                return frozenset()

        if t == "unsafe_block":
            inner = next(
                (c for c in _children(node)
                 if c.type == "block"),
                None,
            )
            return (
                self._block(
                    inner, locals_, param_index, summary
                )
                or frozenset()
            ) if inner is not None else frozenset()
        if t == "macro_invocation":
            # `m!(tokens)` — opaque call; deps = every evaluable
            # token inside the token tree (macros have arbitrary
            # grammar, so a token that fails contributes nothing).
            mname = node.child_by_field_name("macro")
            cname = (
                f"{mname.text.decode()}!"
                if mname is not None else None
            )
            deps = frozenset()
            for c in _children(node):
                if c.type != "token_tree":
                    continue
                for tok in _children(c):
                    try:
                        deps |= self._expr_inner(
                            tok, locals_, param_index, summary
                        )
                    except _Unsupported as exc:
                        deps |= getattr(
                            exc, "partial_deps", frozenset()
                        )
                        continue
            summary.calls.append(
                RustCall(_span(node), cname, (deps,), deps)
            )
            summary.effects = "unknown"
            return deps
        if t in {
            "tuple_expression", "range_expression",
            "array_expression", "struct_expression",
            "field_expression", "index_expression",
            "await_expression", "generic_function",
        }:
            # Containers/member access/`f!()`/`x.await` — union
            # every named child's deps (over-approx: field/index
            # reads carry the receiver's deps). Type and field
            # names are not expressions.
            deps = frozenset()
            for c in _children(node):
                if c.type in _TYPE_NAMES:
                    continue
                try:
                    deps |= self._expr_inner(
                        c, locals_, param_index, summary
                    )
                except _Unsupported as exc:
                    exc.partial_deps = (
                        getattr(exc, "partial_deps", frozenset())
                        | deps
                    )
                    raise
            return deps
        raise _Unsupported("unsupported_expression", _span(node))


_CONTAINER_WRITES = {
    "push", "insert", "extend", "push_front", "push_back",
    "add", "set", "put", "append", "retain", "clear",
}

_TYPE_NAMES = {
    "primitive_type", "type_identifier", "generic_type",
    "scoped_identifier", "field_identifier",
    "shorthand_field_identifier", "type_arguments",
    "type_parameters", "lifetime", "attribute_item",
    "tuple_type", "array_type", "function_type",
    "reference_type", "pointer_type", "unit_type",
    "abstract_type", "trait_bounds", "higher_ranked_trait_bound",
    "removed_trait_bound", "bounded_type", "qualified_type",
    "mutable_specifier", "self_parameter", "visibility_modifier",
    "function_modifiers", "where_clause", "extern_modifier",
}

_EXPR_TYPES = {
    "identifier", "integer_literal", "float_literal",
    "boolean_literal", "char_literal", "string_literal",
    "negative_literal", "unit_expression", "binary_expression",
    "compound_assignment_expr", "unary_expression",
    "reference_expression", "try_expression",
    "parenthesized_expression", "type_cast_expression",
    "prefix_expression", "call_expression",
    "assignment_expression", "if_expression",
    "match_expression", "while_expression", "loop_expression",
    "for_expression", "block", "break_expression",
    "continue_expression", "tuple_expression",
    "range_expression", "array_expression", "struct_expression",
    "field_expression", "index_expression", "await_expression",
    "macro_invocation", "generic_function", "closure_expression",
    "let_condition",
}

# Expression types that carry statement semantics: as an
# `expression_statement`'s inner they keep the `_statement`
# path — their value-less forms return None, which `_expr`
# cannot record.
_STMT_EXPR_TYPES = {
    "if_expression", "match_expression",
    "while_expression", "loop_expression", "for_expression",
    "block", "unsafe_block",
    "break_expression", "continue_expression",
}


def summarize_rust(
    source,
    resolver=None,
    source_path=None,
    module_digests=None,
    resolved_paths=None,
    declared=None,
) -> RustSummarySet:
    if isinstance(source, str):
        source = source.encode()
    if len(source) > MAX_SOURCE_BYTES:
        raise _Unsupported("analysis_limit", 0)
    return _Builder(
        source,
        resolver=resolver,
        source_path=source_path,
        module_digests=module_digests,
        resolved_paths=resolved_paths,
        declared=declared,
    ).build()


def _has_path_attr(item):
    """A `#[path = "..."]` attribute on the item — bodiless
    `mod` declarations only, where it redirects the compiler's
    file lookup outside the resolver contract."""
    sib = item.prev_named_sibling
    while sib is not None and sib.type == "attribute_item":
        if sib.text.replace(b" ", b"").startswith(b"#[path="):
            return True
        sib = sib.prev_named_sibling
    return False


def _mod_base(importer_path):
    """The directory a `mod` declaration resolves beneath: a
    `mod.rs`/`main.rs`/`lib.rs` importer uses its own directory;
    `a.rs` (or a suffix-less synthetic path for an inline `mod`)
    uses `<dir>/a/`."""
    from pathlib import Path

    imp = Path(importer_path)
    if imp.name in {"mod.rs", "main.rs", "lib.rs"}:
        return imp.parent
    return imp.parent / imp.stem


def _fs_resolver(spec, importer_path):
    """Filesystem `mod` resolver for `--resolve-modules`:
    `<base>/<spec>.rs` then `<base>/<spec>/mod.rs`, confined to
    the importer's base tree and MAX_SOURCE_BYTES. Returns the
    resolved Path so the child module resolves its own `mod`
    declarations against its own directory; None leaves the
    declaration opaque."""
    if importer_path is None or not spec:
        return None
    try:
        base = _mod_base(importer_path).resolve()
    except OSError:
        return None
    for cand in (
        base / f"{spec}.rs",
        base / spec / "mod.rs",
    ):
        try:
            real = cand.resolve()
        except OSError:
            continue
        try:
            inside = real.is_relative_to(base)
        except ValueError:
            inside = False
        if not inside or not real.is_file():
            continue
        try:
            if real.stat().st_size <= MAX_SOURCE_BYTES:
                return real
        except OSError:
            continue
    return None


# Opt-in CLI routes — `python -m agent rust-summaries <file>` prints
# the summary set as deterministic JSON on stdout, and
# `python -m agent rust-summaries-accept <file> --manifest <PATH>
# --function <NAME>` accepts one function's declared summary under
# the strict whole-context gate (context key match + the function
# still present in the fresh derivation; `<NAME>` matches the
# emitted name or a bare member name when unambiguous). These change
# no default audit/CLI/MCP route: the analysis stays a conservative
# dependency report, not a proof, verdict or trust gate, and a host
# must invoke the subcommands explicitly. Inputs are bounded — an
# oversized source or manifest is an error, never a silently
# truncated analysis.
ACCEPT_PROFILE = "mumei.rust-summary-accept/v1"
MAX_MANIFEST_BYTES = 8 * 1024 * 1024


def build_parser(parser=None):
    import argparse

    if parser is None:
        parser = argparse.ArgumentParser(
            prog="python -m agent rust-summaries",
            description=(
                "Emit opt-in Rust interprocedural dependency "
                "summaries as JSON — a conservative report, not a "
                "proof or verdict."
            ),
        )
    parser.add_argument(
        "source",
        help="Path to a single Rust source file (at most 64 KiB).",
    )
    parser.add_argument(
        "--resolve-modules",
        action="store_true",
        help=(
            "Resolve `mod NAME;` declarations from the importer's "
            "directory (`<dir>/NAME.rs`, `<dir>/NAME/mod.rs`); "
            "unresolved declarations stay opaque."
        ),
    )
    parser.add_argument(
        "--summary-aware-calls",
        metavar="<MANIFEST>",
        default=None,
        help=(
            "Callee summary manifest "
            "(mumei.rust-scalar-parameter-deps/v1): an opaque call "
            "whose recorded name a manifest entry covers folds the "
            "entry's declared return_dependencies instead of the "
            "opaque every-argument union. The manifest is trusted "
            "as declared; its canonical bytes fold into the "
            "context key."
        ),
    )
    return parser


def build_accept_parser(parser=None):
    """Parser for ``rust-summaries-accept``: the produce route's
    declared inputs plus ``--manifest`` and ``--function`` naming the
    declared manifest and the function whose summary is accepted."""
    parser = build_parser(parser)
    parser.description = (
        "Re-derive the Rust summary set for one declared source "
        "and accept one function's summary under the strict "
        "whole-context gate."
    )
    parser.add_argument(
        "--manifest",
        required=True,
        metavar="<PATH>",
        help=(
            "Summary manifest (mumei.rust-scalar-parameter-deps/v1) "
            "to accept from."
        ),
    )
    parser.add_argument(
        "--function",
        required=True,
        metavar="<NAME>",
        help=(
            "Function whose summary to accept — the emitted name "
            "or a bare member name when it is unambiguous. Accepted "
            "only when the manifest's context key still matches the "
            "fresh derivation and the function survives in it."
        ),
    )
    return parser


def _emit(payload, code):
    import json
    import sys

    print(json.dumps(payload, sort_keys=True))
    sys.exit(code)


def _read_declared_source(path, schema):
    try:
        with open(path, "rb") as handle:
            raw = handle.read(MAX_SOURCE_BYTES + 1)
    except OSError as exc:
        _emit(
            {
                "schema_version": schema,
                "error": {
                    "reason": "source_unreadable",
                    "detail": exc.strerror or str(exc),
                },
            },
            2,
        )
    if len(raw) > MAX_SOURCE_BYTES:
        _emit(
            {
                "schema_version": schema,
                "error": {
                    "reason": "source_too_large",
                    "limit_bytes": MAX_SOURCE_BYTES,
                },
            },
            2,
        )
    return raw


def _reject_overwrite(output, declared_paths, schema):
    """`--output` may not overwrite a declared input — writing the
    report would destroy the bytes the report describes."""
    import os
    from pathlib import Path

    if output is None:
        return
    for declared in declared_paths:
        try:
            same = (
                Path(output).resolve() == Path(declared).resolve()
            )
        except RuntimeError:
            same = True
        if not same:
            try:
                same = os.path.samefile(output, declared)
            except OSError:
                same = False
        if same:
            _emit(
                {
                    "schema_version": schema,
                    "error": {
                        "reason": "output_overwrites_source",
                        "detail": (
                            "declared output path would overwrite a "
                            "declared input"
                        ),
                    },
                },
                2,
            )


CHECK_PROFILE = "mumei.rust-summary-check/v1"


def build_check_parser(parser=None):
    """Parser for ``rust-summaries-check``: the produce route's
    declared inputs plus ``--manifest`` naming the summary manifest
    to check and ``--output`` for the check report."""
    parser = build_parser(parser)
    parser.description = (
        "Re-derive the Rust summary set for one declared source "
        "and check a declared manifest's functions against it."
    )
    parser.add_argument(
        "--manifest",
        required=True,
        metavar="<PATH>",
        help=(
            "Summary manifest (mumei.rust-scalar-parameter-deps/v1) "
            "to check."
        ),
    )
    parser.add_argument(
        "--output",
        metavar="<PATH>",
        help="Write the check report JSON here instead of stdout.",
    )
    return parser


def build_reuse_parser(parser=None):
    """Parser for ``rust-summaries-reuse``: the produce route's
    declared inputs plus ``--manifest`` naming the manifest to reuse
    from and ``--output`` for the merged manifest."""
    parser = build_check_parser(parser)
    parser.description = (
        "Re-derive the Rust summary set for one declared source "
        "and emit a manifest that reuses a declared manifest's "
        "unchanged summaries."
    )
    for action in parser._actions:
        if action.dest == "manifest":
            action.help = (
                "Summary manifest (mumei.rust-scalar-parameter-deps/v1) "
                "to reuse unchanged summaries from."
            )
        elif action.dest == "output":
            action.help = (
                "Write the merged manifest JSON here instead of "
                "stdout."
            )
    return parser


def _read_declared_manifest(path, schema=ACCEPT_PROFILE):

    import json

    try:
        with open(path, "rb") as handle:
            blob = handle.read(MAX_MANIFEST_BYTES + 1)
    except OSError as exc:
        _emit(
            {
                "schema_version": schema,
                "error": {
                    "reason": "manifest_unreadable",
                    "detail": exc.strerror or str(exc),
                },
            },
            2,
        )
    if len(blob) > MAX_MANIFEST_BYTES:
        _emit(
            {
                "schema_version": schema,
                "error": {
                    "reason": "manifest_too_large",
                    "limit_bytes": MAX_MANIFEST_BYTES,
                },
            },
            2,
        )
    try:
        return RustSummarySet.from_dict(json.loads(blob))
    except (TypeError, UnicodeDecodeError):
        _emit(
            {
                "schema_version": schema,
                "error": {
                    "reason": "manifest_malformed",
                    "detail": "declared summary manifest is malformed",
                },
            },
            2,
        )
    except ValueError as exc:
        _emit(
            {
                "schema_version": schema,
                "error": {
                    "reason": "manifest_malformed",
                    "detail": str(exc),
                },
            },
            2,
        )


def _callee_manifest(args, schema=PROFILE):
    """The `--summary-aware-calls` manifest — declared, trusted
    as asserted; malformed fails statically like the primary
    manifest."""
    path = getattr(args, "summary_aware_calls", None)
    if path is None:
        return None
    return _read_declared_manifest(path, schema)


def _declared_input_paths(args) -> list:
    """Every declared input the route consumes — `--output` may
    not overwrite one."""
    paths = [args.source]
    for extra in ("manifest", "summary_aware_calls"):
        path = getattr(args, extra, None)
        if path is not None:
            paths.append(path)
    return paths


def _summarize_declared(
    raw, schema, resolver=None, source_path=None, resolved=None,
    declared=None,
):
    try:
        return summarize_rust(
            raw,
            resolver=resolver,
            source_path=source_path,
            resolved_paths=resolved,
            declared=declared,
        )
    except _Unsupported as exc:
        _emit(
            {
                "schema_version": schema,
                "error": {"reason": exc.reason},
            },
            2,
        )


def _resolver_for(args):
    """The filesystem resolver for `--resolve-modules` — shared by
    every route that re-derives the live summary set so a resolved
    manifest's context key matches across produce, check, reuse
    and accept."""
    if getattr(args, "resolve_modules", False):
        return _fs_resolver
    return None


def main(args=None) -> None:
    import json

    if args is None:
        args = build_parser().parse_args()
    raw = _read_declared_source(args.source, PROFILE)
    resolver = _resolver_for(args)
    print(
        json.dumps(
            _summarize_declared(
                raw,
                PROFILE,
                resolver=resolver,
                source_path=args.source,
                declared=_callee_manifest(args),
            ).to_dict(),
            sort_keys=True,
        )
    )


def summary_accept_document(declared, live, function) -> dict:
    """The ``mumei.rust-summary-accept/v1`` acceptance document.

    Shared by ``rust-summaries-accept`` and the
    ``rust_summaries_accept`` MCP tool so both emit the identical
    decision: the strict whole-context gate (`context_match`), then
    a declared-only function resolution that emits the freshly
    derived record — never the declared one, so the manifest-forgery
    channel is closed.
    """
    report = {
        "schema_version": ACCEPT_PROFILE,
        "accepted": False,
        "function": function,
        "context_match": declared.context_key == live.context_key,
    }
    if not report["context_match"]:
        report["reason"] = "context_mismatch"
    else:
        # Emit the freshly derived record, never the declared one —
        # identical for honest manifests, and removes the manifest-
        # forgery channel entirely. A bare member name must resolve
        # to exactly one function. An exact match on the emitted name
        # (`f`, `P.f`) wins over the bare-member-name fallback; the
        # fallback compares name stems, so `P.f#2` also answers to `f`
        # and an undiscriminated name stays ambiguous.
        matches = [
            f for f in live.functions if f.name == function
        ]
        if not matches:
            matches = [
                f
                for f in live.functions
                if f.name.rsplit(".", 1)[-1].split("#", 1)[0]
                == function
            ]
        if not matches:
            report["reason"] = "unknown_function"
        elif len(matches) > 1:
            report["reason"] = "ambiguous_function"
        elif matches[0].name not in {
            f.name for f in declared.functions
        }:
            # The strict gate accepts declared summaries only —
            # a function absent from the manifest cannot be
            # accepted however fresh the context.
            report["reason"] = "undeclared_function"
        else:
            report["accepted"] = True
            report["summary"] = matches[0].to_dict()
    return report


def main_accept(args=None) -> None:
    if args is None:
        args = build_accept_parser().parse_args()
    declared = _read_declared_manifest(args.manifest)
    raw = _read_declared_source(args.source, ACCEPT_PROFILE)
    live = _summarize_declared(
        raw,
        ACCEPT_PROFILE,
        resolver=_resolver_for(args),
        source_path=args.source,
        declared=_callee_manifest(args, ACCEPT_PROFILE),
    )
    _emit(
        summary_accept_document(declared, live, args.function), 0
    )


def _reuse_partition(declared, live):
    """Partition the manifest's functions against the fresh set.

    `reusable` — the name survives and the record is identical
    (derivation is deterministic, so an unchanged function derives
    the same record); `stale` — the name survives but the record
    differs; `missing` — the fresh set no longer produces the name.
    Detection only.
    """
    live_by_name = {}
    for f in live.functions:
        live_by_name.setdefault(f.name, f)
    reusable, stale, missing = [], [], []
    for entry in declared.functions:
        fresh = live_by_name.get(entry.name)
        if fresh is None:
            missing.append(entry.name)
        elif fresh == entry:
            reusable.append(entry.name)
        else:
            stale.append(entry.name)
    return reusable, stale, missing


def summary_check_document(declared, live) -> dict:
    """The ``mumei.rust-summary-check/v1`` comparison document.

    Shared by ``rust-summaries-check`` and the ``rust_summaries_check``
    MCP tool so both emit the identical partition: `context_match`
    (the strict whole-context gate) plus the name-level
    `reusable`/`stale`/`missing` sets. Detection only — what to
    recompute is the host's call.
    """
    reusable, stale, missing = _reuse_partition(declared, live)
    return {
        "schema_version": CHECK_PROFILE,
        "context_match": declared.context_key == live.context_key,
        "reusable": sorted(reusable),
        "stale": sorted(stale),
        "missing": sorted(missing),
    }


def main_check(args=None) -> None:
    """Check a declared manifest against a fresh summary set.

    Emits ``mumei.rust-summary-check/v1``: whether the declared
    context key still matches (the strict whole-context gate) and a
    name-level partition of the manifest's functions — `reusable`
    (identical record survives), `stale` (same name, different
    record) and `missing` (the fresh set no longer produces the
    name). Detection only — what to recompute is the host's call.
    """
    import json

    if args is None:
        args = build_check_parser().parse_args()
    declared = _read_declared_manifest(args.manifest, CHECK_PROFILE)
    raw = _read_declared_source(args.source, CHECK_PROFILE)
    _reject_overwrite(
        getattr(args, "output", None),
        _declared_input_paths(args),
        CHECK_PROFILE,
    )
    resolved: set = set()
    live = _summarize_declared(
        raw,
        CHECK_PROFILE,
        resolver=_resolver_for(args),
        source_path=args.source,
        resolved=resolved,
        declared=_callee_manifest(args, CHECK_PROFILE),
    )
    _reject_overwrite(
        getattr(args, "output", None), resolved, CHECK_PROFILE
    )
    document = json.dumps(
        summary_check_document(declared, live), sort_keys=True
    )
    if getattr(args, "output", None):
        with open(args.output, "w") as handle:
            handle.write(document + "\n")
    else:
        print(document)


def summary_reuse_set(declared, live) -> RustSummarySet:
    """The merged summary set emitted by ``rust-summaries-reuse``.

    Shared by ``rust-summaries-reuse`` and the
    ``rust_summaries_reuse`` MCP tool so both emit the identical
    manifest: a declared function whose record is identical under the
    fresh derivation is reused verbatim, every other live function is
    freshly derived and a `missing` entry is dropped. The emitted set
    is keyed to the fresh context — per-function reuse stays the
    host's weaker freshness choice, never the strict whole-context
    gate.
    """
    reusable, _, _ = _reuse_partition(declared, live)
    declared_by_name = {f.name: f for f in declared.functions}
    merged = [
        declared_by_name.get(f.name, f) if f.name in reusable else f
        for f in live.functions
    ]
    return RustSummarySet(
        live.context_key,
        PROFILE,
        merged,
        call_modeling=live.call_modeling,
    )


def main_reuse(args=None) -> None:
    """Emit a manifest reusing a declared manifest's unchanged
    summaries.

    Same partition as ``rust-summaries-check``: a declared function
    whose record is identical under the fresh derivation is reused
    verbatim, every other live function is freshly derived and a
    `missing` entry is dropped. The emitted set is keyed to the fresh
    context — per-function reuse stays the host's weaker freshness
    choice, never the strict whole-context gate.
    """
    import json

    if args is None:
        args = build_reuse_parser().parse_args()
    declared = _read_declared_manifest(args.manifest, CHECK_PROFILE)
    raw = _read_declared_source(args.source, CHECK_PROFILE)
    _reject_overwrite(
        getattr(args, "output", None),
        _declared_input_paths(args),
        CHECK_PROFILE,
    )
    resolved: set = set()
    live = _summarize_declared(
        raw,
        CHECK_PROFILE,
        resolver=_resolver_for(args),
        source_path=args.source,
        resolved=resolved,
        declared=_callee_manifest(args, CHECK_PROFILE),
    )
    _reject_overwrite(
        getattr(args, "output", None), resolved, CHECK_PROFILE
    )
    document = json.dumps(
        summary_reuse_set(declared, live).to_dict(),
        sort_keys=True,
    )
    if getattr(args, "output", None):
        with open(args.output, "w") as handle:
            handle.write(document + "\n")
    else:
        print(document)


ATTEMPT_REQUEST_PROFILE = "mumei.rust-summaries-attempt-request/v1"
ATTEMPT_REPORT_PROFILE = "mumei.rust-summaries-attempt-report/v1"


def build_attempt_parser(parser=None):
    """Parser for ``rust-summaries-attempt``: the produce route's
    declared inputs plus the attempt's own declared timeout and an
    optional memory bound."""
    parser = build_parser(parser)
    parser.description = (
        "Run the rust-summaries produce route as one declared attempt "
        "and emit the reconciled lineage descriptors."
    )
    parser.add_argument(
        "--attempt-timeout",
        type=int,
        required=True,
        metavar="<MS>",
        help="Declared attempt bound in milliseconds (required).",
    )
    parser.add_argument(
        "--memory-bound-mb",
        type=int,
        default=None,
        metavar="<MB>",
        help=(
            "Optional declared POSIX RLIMIT_AS ceiling applied to the "
            "attempt child's whole address space."
        ),
    )
    parser.add_argument(
        "--output",
        metavar="<PATH>",
        help="Write the attempt report JSON here instead of stdout.",
    )
    return parser


def _attempt_fingerprint(
    source_path: str, raw: bytes, summary_aware_calls=None
) -> str:
    """Bind the request's declared inputs into one request identity.

    A declared callee manifest is a request input like the source —
    its bytes fold in so a swapped manifest yields a different
    fingerprint. An unreadable manifest raises ``ValueError`` —
    the request cannot be bound to bytes it does not have."""
    import hashlib
    import json
    from pathlib import Path

    request_doc = {
        "schema_version": ATTEMPT_REQUEST_PROFILE,
        "source": {
            "path": source_path,
            "sha256": hashlib.sha256(raw).hexdigest(),
        },
    }
    if summary_aware_calls is not None:
        try:
            with open(summary_aware_calls, "rb") as handle:
                manifest_raw = handle.read(MAX_MANIFEST_BYTES + 1)
        except OSError as exc:
            # `str(exc)` would carry the checkout-local path into
            # the attempt report's error detail.
            raise ValueError(
                "declared callee manifest unreadable: "
                f"{exc.strerror or 'I/O error'}"
            ) from exc
        if len(manifest_raw) > MAX_MANIFEST_BYTES:
            raise ValueError("declared callee manifest too large")
        request_doc["callee_manifest"] = {
            "path": summary_aware_calls,
            "sha256": hashlib.sha256(manifest_raw).hexdigest(),
        }
    return hashlib.sha256(
        json.dumps(
            request_doc, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def run_attempt(
    source_path,
    raw,
    attempt_timeout,
    memory_bound_mb=None,
    summary_aware_calls=None,
):
    """Run the produce route as one declared attempt → report dict.

    Shared by ``rust-summaries-attempt`` and the
    ``rust_summaries_attempt`` MCP tool so both run the identical
    C11 lifecycle: a fresh ``AttemptSequence`` keyed to the request
    fingerprint (the declared source's bytes), one reserved attempt
    observed by ``dispatch_attempt`` under ``attempt_timeout``,
    reconcile and compare-and-set publication — an ``exited`` run's
    captured stdout becomes the selected result only when every
    declared input byte is unchanged after the observed run.
    Returns the ``mumei.rust-summaries-attempt-report/v1`` document;
    raises ``ValueError`` on a lifecycle failure.
    """
    import sys
    from pathlib import Path

    from agent.attempt_runner import dispatch_attempt
    from agent.verification_attempt import (
        AttemptSequence,
        AttemptSequenceStore,
    )

    fingerprint = _attempt_fingerprint(
        source_path, raw, summary_aware_calls=summary_aware_calls
    )
    argv = [
        sys.executable,
        "-m",
        "agent",
        "rust-summaries",
        source_path,
    ]
    if summary_aware_calls is not None:
        argv += ["--summary-aware-calls", summary_aware_calls]
    argv = tuple(argv)
    sequence = AttemptSequence(fingerprint, attempt_timeout)
    store = AttemptSequenceStore()
    store.publish(sequence)
    current = store.current
    dispatch = dispatch_attempt(
        current.begin_attempt(),
        argv,
        memory_bound_mb=memory_bound_mb,
    )
    try:
        drifted = (
            _attempt_fingerprint(
                source_path,
                Path(source_path).read_bytes(),
                summary_aware_calls=summary_aware_calls,
            )
            != fingerprint
        )
    except (OSError, ValueError):
        drifted = True
    if dispatch.run.record.state == "exited" and not drifted:
        updated = dispatch.sequence.select_result(
            dispatch.captured_output()
        )
    else:
        updated = dispatch.sequence
    published = store.compare_and_set(current, updated)
    report = {
        "schema_version": ATTEMPT_REPORT_PROFILE,
        "sequence": published.to_dict(),
        "normalized": dispatch.run.normalized().to_dict(),
    }
    if published.selected_result is not None:
        report["candidate"] = published.evidence_candidate().to_dict()
    return report


def main_attempt(args=None) -> None:
    """Run the produce route as one declared attempt.

    Spawns ``python -m agent rust-summaries <source>`` through the
    C11 dispatch lifecycle: a fresh ``AttemptSequence`` keyed to the
    request fingerprint (the declared source's bytes), one reserved
    attempt observed by ``dispatch_attempt`` under
    ``--attempt-timeout``, reconcile and compare-and-set
    publication — an ``exited`` run's captured stdout becomes the
    selected result only when every declared input byte is unchanged
    after the observed run. Emits
    ``mumei.rust-summaries-attempt-report/v1`` — the canonical
    lineage, the normalized run-result descriptor and, only when a
    result was selected, the
    ``mumei.verifier-evidence-candidate/v1`` descriptor.
    """
    import json
    import sys

    if args is None:
        args = build_attempt_parser().parse_args()
    _reject_overwrite(
        args.output, _declared_input_paths(args), ATTEMPT_REPORT_PROFILE
    )
    raw = _read_declared_source(args.source, ATTEMPT_REPORT_PROFILE)
    if getattr(args, "resolve_modules", False):
        _emit(
            {
                "schema_version": ATTEMPT_REPORT_PROFILE,
                "error": {
                    "reason": "unsupported_option",
                    "detail": (
                        "--resolve-modules resolves files "
                        "implicitly; the attempt request "
                        "fingerprint cannot bind undeclared bytes"
                    ),
                },
            },
            2,
        )
    try:
        report = run_attempt(
            args.source,
            raw,
            args.attempt_timeout,
            memory_bound_mb=args.memory_bound_mb,
            summary_aware_calls=getattr(args, "summary_aware_calls", None),
        )
    except ValueError as exc:
        _emit(
            {
                "schema_version": ATTEMPT_REPORT_PROFILE,
                "error": {"reason": "attempt_failed", "detail": str(exc)},
            },
            2,
        )
    document = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(document)
    else:
        sys.stdout.write(document)
