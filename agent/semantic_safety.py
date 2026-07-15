"""Deterministic type/constant semantic model for foreign-code safety inference.

Layer B safety-condition inference (divide-by-zero, integer overflow, array
bounds, nil/null dereference) used to false-positive on a handful of patterns
that a purely syntactic scan cannot rule out:

* ``#281`` a method-call/member-access receiver (``result + SafeCast.toUint(...)``)
  modeled as a free integer addend;
* ``#295`` a ``!= nil`` / ``!= null`` contract attached to a value type that can
  never be null (Go ``reflect.Value``, Solidity ``bytes``/``string``, Rust
  references);
* ``#296`` a divide-by-zero / negative-index counterexample invented for a
  divisor / index that is actually a declared ``constant``/``immutable`` (Rust
  ``const``, TypeScript ``const``) with a known non-zero / non-negative value.

Those were previously handled by scattered per-language special cases. This
module gathers the shared decisions behind one small set of **type predicates**
and a cross-language **constant model** so every safety heuristic consults the
same semantic facts.

Everything here is a pure, deterministic analysis: it never calls an LLM and
never shells out to ``solc`` / ``rustc`` / ``tsc``, so the no-LLM /
``CI_FIXTURE_MODE`` fixture path returns identical results. When type or
constant information is unavailable the predicates fall back to the conservative
answer (treat the operand as a free variable / treat the value as nullable), so
the safety condition is still emitted and Z3 soundness is never weakened by a
false negative.
"""
from __future__ import annotations

import re

_LANGUAGE_ALIASES = {
    "py": "python",
    "rs": "rust",
    "ts": "typescript",
    "tsx": "typescript",
    "javascript": "typescript",
    "js": "typescript",
    "jsx": "typescript",
    "golang": "go",
    "sol": "solidity",
}


def normalize_language(language: str) -> str:
    canonical = language.strip().lower()
    return _LANGUAGE_ALIASES.get(canonical, canonical)


# --------------------------------------------------------------------------- #
# Constant model (#296): declared ``constant``/``immutable``/``const`` values.
# --------------------------------------------------------------------------- #

_SOLIDITY_CONST_RE = re.compile(
    r"\b(?:u?int\d*|address|bytes\d*|bool)\s+"
    r"(?:(?:public|private|internal|external)\s+)*"
    r"(?:constant|immutable)\s+"
    r"(?P<name>[A-Za-z_]\w*)\s*=\s*(?P<value>[^;]+);"
)
# Rust ``const NAME: TYPE = LITERAL;`` (also ``static``/``static mut``).
_RUST_CONST_RE = re.compile(
    r"\b(?:const|static(?:\s+mut)?)\s+"
    r"(?P<name>[A-Za-z_]\w*)\s*:\s*[^=;]+=\s*(?P<value>[^;]+);"
)
# TypeScript ``const NAME = LITERAL`` (optional type annotation / ``as const``).
_TS_CONST_RE = re.compile(
    r"\bconst\s+(?P<name>[A-Za-z_$][\w$]*)\s*(?::\s*[^=]+?)?=\s*(?P<value>[^;,\n]+)"
)

_CONST_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "solidity": (_SOLIDITY_CONST_RE,),
    "rust": (_RUST_CONST_RE,),
    "typescript": (_TS_CONST_RE,),
}


def parse_int_literal(text: str) -> int | None:
    """Parse a hex/decimal integer literal, ignoring ``_`` separators and casts."""
    text = text.strip()
    # Drop a trailing cast/suffix such as ``as const`` or a Rust type suffix.
    text = re.split(r"\s+as\b", text, maxsplit=1)[0].strip()
    text = re.split(r"[iu](?:8|16|32|64|128|size)$", text, maxsplit=1)[0].strip()
    text = text.replace("_", "")
    try:
        return int(text, 16) if text.lower().startswith("0x") else int(text, 10)
    except ValueError:
        return None


def collect_declared_constants(source: str, language: str) -> dict[str, int]:
    """Map declared integer ``constant``/``immutable``/``const`` names to their value.

    Used so the divide-by-zero and out-of-bounds heuristics do not model a named
    constant (a curve order ``N``, a radix ``EVM_TREE_RADIX``) as a free Z3
    integer that can be chosen as ``0`` / ``-1`` (#296). Non-integer or
    non-literal initializers (expressions referencing other constants) are
    skipped so only values we can reason about are pinned.
    """
    constants: dict[str, int] = {}
    for pattern in _CONST_PATTERNS.get(normalize_language(language), ()):  # noqa: E501
        for match in pattern.finditer(source):
            value = parse_int_literal(match.group("value"))
            if value is not None:
                # First declaration wins, mirroring source order.
                constants.setdefault(match.group("name"), value)
    return constants


def divisor_provably_nonzero(name: str, known_constants: dict[str, int]) -> bool:
    """True when ``name`` is a declared constant with a known non-zero value (#296)."""
    return known_constants.get(name, 0) != 0


def known_nonnegative_index(name: str, known_constants: dict[str, int]) -> int | None:
    """Return a declared constant index value when it is provably non-negative.

    A pinned index (e.g. ``decoded[EVM_TREE_RADIX]``, ``EVM_TREE_RADIX == 16``)
    stops Z3 inventing an impossible negative index; the upper bound remains a
    genuine concern, so callers still check ``index < len`` (#296).
    """
    value = known_constants.get(name)
    if value is None or value < 0:
        return None
    return value


# --------------------------------------------------------------------------- #
# Type predicates (#295): which values can actually be nil / null.
# --------------------------------------------------------------------------- #

# Go types that can hold a nil value and therefore be nil-dereferenced. A bare
# named/qualified type (``reflect.Value``, ``time.Time``) is a value type here
# and is intentionally treated as non-nillable.
_GO_NILLABLE_TYPE_RE = re.compile(
    r"^(?:"
    r"\*"  # pointer *T
    r"|\[\]"  # slice []T
    r"|map\["  # map[K]V
    r"|chan\b"  # chan T
    r"|<-"  # <-chan T
    r"|func\b"  # func(...) ...
    r"|interface\s*\{"  # interface{ ... }
    r"|any\b"
    r"|error\b"
    r")"
)

# TypeScript primitive value types that are never null when non-optional; a
# ``.length``/``.len`` access on them is not a null-dereference concern.
_TS_NON_NULLABLE_PRIMITIVES = frozenset(
    {"number", "boolean", "bigint", "void", "never", "symbol"}
)


def go_type_is_nillable(raw_type: str) -> bool:
    return bool(_GO_NILLABLE_TYPE_RE.match(raw_type.strip()))


def is_nullable_type(raw_type: str, language: str) -> bool:
    """True when a value of ``raw_type`` in ``language`` can be nil / null.

    Only nullable types warrant a ``!= nil`` / ``!= null`` safety contract.
    Value types (Go structs, Solidity ``bytes``/``string``/``uint``, Rust
    references, TypeScript primitives) can never be null, so emitting one is a
    false positive (#295). An empty / unknown ``raw_type`` returns the
    language default so callers stay conservative.
    """
    canonical = normalize_language(language)
    normalized = raw_type.strip()
    if not normalized:
        return language_default_nullable(canonical)
    if canonical == "go":
        return go_type_is_nillable(normalized)
    if canonical == "typescript":
        lowered = normalized.rstrip("?").strip().lower()
        return lowered not in _TS_NON_NULLABLE_PRIMITIVES
    # Rust references / Option-based nullability and Solidity value types never
    # participate in a bare null dereference.
    return False


def language_default_nullable(language: str) -> bool:
    """Whether an unknown-typed value is treated as nullable in ``language``.

    TypeScript/JavaScript values are conservatively nullable (``x!.length``
    asserts a possible null). Go nil-dereference is decided per-parameter by
    :func:`is_nullable_type`, so an unknown Go type defaults to non-nillable to
    avoid flagging value-type receivers. Rust/Solidity have no bare null.
    """
    return normalize_language(language) == "typescript"


def should_flag_null_deref(
    name: str,
    param_types: dict[str, str] | None,
    language: str,
) -> bool:
    """Decide whether a ``.length``/``.len`` receiver needs a non-null contract.

    Uses the declared parameter type when available and falls back to the
    language default otherwise, so the decision is driven by one type predicate
    instead of per-language branches.
    """
    if param_types and name in param_types:
        return is_nullable_type(param_types[name], language)
    return language_default_nullable(language)
