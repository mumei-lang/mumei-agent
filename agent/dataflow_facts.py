"""Function-local dataflow / path-sensitive facts (Layer B stage 3).

This module is the third input to the foreign-code safety heuristics, next to
:func:`agent.tree_sitter_extract.analyze_expression` (syntactic facts about a
single expression) and :mod:`agent.semantic_safety` (type predicates and the
declared-constant model). It walks the statement tree produced by
:func:`agent.tree_sitter_extract.extract_statements` and computes, for every
``return`` statement, the set of facts that *must* hold on every path reaching
it:

* constant folding of ``const`` declarations and arithmetic initialisers
  (:func:`evaluate_constant_expression`, :func:`fold_constants`);
* guard propagation from ``if`` / early ``return`` / loop conditions /
  ``switch`` cases (``x != 0``, ``x != nil``, ``0 <= i < len(xs)``, ...);
* reaching definitions for divisors and indices (``n := len(xs) - 1``,
  ``i := x % len(xs)``, ``x := 3``);
* local aliases of slices / pointers (``ys := xs`` or ``ys := make([]T, len(xs))``
  share their length with ``xs``; ``p := &v`` is non-nil).

Facts are "must" facts: branches are merged by intersection and every
assignment kills the facts mentioning the assigned name, so a missing fact only
ever makes the consumer *more* conservative (a false positive), never less.
Everything here is deterministic, needs no LLM and no external compiler, and
returns ``None`` whenever tree-sitter cannot parse the body so callers keep
their regex fallbacks.

The same walk also derives the resource / initialisation facts behind the
new bug categories (nil-map assignment, lock held at return / double lock,
resource opened but never released). Unlike the safety facts these are
*may*-path findings: a single path on which the map is still nil / the lock
is still held / the handle is still open at the exit is reported, because a
handle that is definitely held on that path is a bug on that path. Merges
intersect the held sets, so a resource released on one branch of an ``if`` is
not reported after the join.

Bodies containing ``goto`` are not analysed (``None``), since a label can
re-enter any point of the function.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from fractions import Fraction

from agent import tree_sitter_extract

_MAX_I64 = 9_223_372_036_854_775_807
_MIN_I64 = -9_223_372_036_854_775_808

_NUMERIC_CASTS = {
    "int", "int8", "int16", "int32", "int64",
    "uint", "uint8", "uint16", "uint32", "uint64", "uintptr",
    "float32", "float64", "byte", "rune",
}

_GO_INT_TYPES = _NUMERIC_CASTS - {"float32", "float64"}
GO_UNSIGNED_TYPES = frozenset(
    {"uint", "uint8", "uint16", "uint32", "uint64", "uintptr", "byte"}
)

_LOCK_METHODS = {"Lock", "RLock"}
# Calls whose integer result is documented to be non-negative.
_NONNEG_CALLS = re.compile(
    r"^(?:len|cap|copy|sort\.Search\w*|sortSearch|bits\.(?:Len|OnesCount|TrailingZeros|LeadingZeros)\w*|"
    r"strings\.Count|bytes\.Count|utf8\.RuneCount\w*)\("
)
# Calls that read from / write to a handle without taking ownership of it.
_BORROWING_CALLS = re.compile(
    r"\b(?:io\.(?:ReadAll|Copy|CopyN|ReadFull|ReadAtLeast|WriteString)|"
    r"fmt\.F(?:print|printf|println|scan|scanf|scanln)|"
    r"bufio\.New(?:Scanner|Reader|Writer|ReaderSize|WriterSize)|"
    r"json\.New(?:Decoder|Encoder)|csv\.New(?:Reader|Writer)|"
    r"ioutil\.ReadAll)\s*\("
)
_OPEN_CALLS = re.compile(
    r"^(?:os\.(?:Open|OpenFile|Create|CreateTemp)|net\.(?:Dial|DialTimeout|Listen)|"
    r"os\.Pipe)\s*\("
)


# ---------------------------------------------------------------------------
# Constant folding
# ---------------------------------------------------------------------------


def evaluate_constant_expression(
    expr: str, values: dict[str, Fraction]
) -> Fraction | None:
    """Safely evaluate a constant arithmetic expression.

    Supports ``+``, ``-``, ``*``, ``/``, ``%``, ``<<``, ``>>``, ``|``, ``&``,
    ``^``, parentheses, numeric literals (decimal, hex, binary, octal, float
    with exponent/underscores), numeric casts such as ``int64(x)`` and
    references to already-known constants (``values``).  The result is a
    ``Fraction`` so floating-point intermediates (e.g. ``365.2425``) stay exact
    until a final integer conversion is requested.
    """
    expr = expr.strip()
    if not expr:
        return None
    try:
        tree = ast.parse(expr, mode="eval")
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return None

    def _constant_value(node: ast.Constant) -> Fraction | None:
        if isinstance(node.value, bool):
            return None
        if isinstance(node.value, int):
            return Fraction(node.value)
        if isinstance(node.value, float):
            text = ast.get_source_segment(expr, node)
            if text is None:
                text = str(node.value)
            try:
                return Fraction(text.replace("_", ""))
            except ValueError:
                return None
        return None

    def _eval(node: ast.AST) -> Fraction | None:
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant):
            return _constant_value(node)
        if isinstance(node, ast.Name):
            return values.get(node.id)
        if isinstance(node, ast.Attribute):
            base = node.value
            if isinstance(base, ast.Name):
                return values.get(f"{base.id}.{node.attr}")
            return None
        if isinstance(node, ast.Call):
            if (
                isinstance(node.func, ast.Name)
                and node.func.id in _NUMERIC_CASTS
                and len(node.args) == 1
            ):
                return _eval(node.args[0])
            return None
        if isinstance(node, ast.BinOp):
            left = _eval(node.left)
            right = _eval(node.right)
            if left is None or right is None:
                return None
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, (ast.Div, ast.FloorDiv)):
                if right == 0:
                    return None
                if left.denominator == 1 and right.denominator == 1:
                    # Go integer division truncates toward zero.
                    return Fraction(int(left / right))
                return left / right
            if isinstance(node.op, ast.Mod):
                if right == 0 or left.denominator != 1 or right.denominator != 1:
                    return None
                quotient = int(left / right)
                return left - right * quotient
            if isinstance(node.op, ast.Pow):
                if right.denominator != 1:
                    return None
                exp = int(right)
                if exp < 0 or exp > 64:
                    return None
                return left ** exp
            if left.denominator != 1 or right.denominator != 1:
                return None
            if isinstance(node.op, ast.LShift):
                if right < 0 or right > 128:
                    return None
                return Fraction(int(left) << int(right))
            if isinstance(node.op, ast.RShift):
                if right < 0 or right > 128:
                    return None
                return Fraction(int(left) >> int(right))
            if isinstance(node.op, ast.BitOr):
                return Fraction(int(left) | int(right))
            if isinstance(node.op, ast.BitAnd):
                return Fraction(int(left) & int(right))
            if isinstance(node.op, ast.BitXor):
                return Fraction(int(left) ^ int(right))
            return None
        if isinstance(node, ast.UnaryOp):
            operand = _eval(node.operand)
            if operand is None:
                return None
            if isinstance(node.op, ast.UAdd):
                return +operand
            if isinstance(node.op, ast.USub):
                return -operand
            if isinstance(node.op, ast.Invert) and operand.denominator == 1:
                return Fraction(~int(operand))
            return None
        return None

    return _eval(tree)


def fold_constants(
    declarations: list[tuple[str, str]], base: dict[str, int] | None = None
) -> dict[str, int]:
    """Resolve ``(name, initializer)`` pairs to integer values, iterating to a fixpoint.

    ``base`` supplies constants that are already known (e.g. package-level
    declarations). Initialisers that reference other declared constants are
    resolved in dependency order regardless of their textual order. Values
    outside the ``int64`` range and non-integral results are skipped so the
    caller keeps treating those names as unknown (conservative).
    """
    values: dict[str, Fraction] = {
        name: Fraction(value) for name, value in (base or {}).items()
    }
    resolved: dict[str, int] = dict(base or {})
    pending = [(name, init) for name, init in declarations if init.strip()]
    changed = True
    while changed and pending:
        changed = False
        remaining: list[tuple[str, str]] = []
        for name, init in pending:
            evaluated = evaluate_constant_expression(init, values)
            if evaluated is not None and evaluated.denominator == 1:
                int_value = int(evaluated)
                if _MIN_I64 <= int_value <= _MAX_I64:
                    values[name] = evaluated
                    resolved[name] = int_value
                    changed = True
                    continue
            remaining.append((name, init))
        pending = remaining
    return resolved


# ---------------------------------------------------------------------------
# Fact environment
# ---------------------------------------------------------------------------


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _parse_int(text: str) -> int | None:
    text = _norm(text).replace("_", "")
    if not text:
        return None
    negative = text.startswith("-")
    if negative:
        text = text[1:]
    try:
        if re.fullmatch(r"0[xX][0-9a-fA-F]+", text):
            value = int(text, 16)
        elif re.fullmatch(r"0[bB][01]+", text):
            value = int(text, 2)
        elif re.fullmatch(r"0[oO][0-7]+", text):
            value = int(text[2:], 8)
        elif re.fullmatch(r"0[0-7]+", text):
            value = int(text, 8)
        elif re.fullmatch(r"\d+", text):
            value = int(text)
        else:
            return None
    except ValueError:
        return None
    return -value if negative else value


_IDENT = r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*"
_LEN_EXPR = re.compile(rf"^len\(({_IDENT})\)$")
_LEN_ARITH = re.compile(rf"^len\(({_IDENT})\)([+-])(\w+)$")
_LEN_DIV = re.compile(rf"^len\(({_IDENT})\)(?:/|>>)(\w+)$")
_PAREN_LEN_ARITH = re.compile(rf"^\(len\(({_IDENT})\)([+-])(\w+)\)(?:/|>>)(\w+)$")
_MOD_LEN = re.compile(rf"^({_IDENT})%(?:{'|'.join(sorted(_GO_INT_TYPES))})?\(?len\(({_IDENT})\)\)?$")
_MOD_CONST = re.compile(rf"^({_IDENT})%(\w+)$")
_BIT_AND = re.compile(rf"^({_IDENT})&(\w+)$")
_SIMPLE_ARITH = re.compile(rf"^({_IDENT})([+\-*/])(\w+)$")
_MAKE_LEN = re.compile(rf"^make\(\[\][^,]+,\s*len\(({_IDENT})\)(?:,[^)]*)?\)$")
_MAKE_SIZE = re.compile(r"^make\(\[\][^,]+,\s*(\w+)(?:,[^)]*)?\)$")
_MAKE_GROW = re.compile(rf"^make\(\[\][^,]+,\s*({_IDENT})\+(\w+)(?:,[^)]*)?\)$")
_COMPOSITE = re.compile(r"^(?:&?\[\][^{]+|&?map\[[^\]]+\][^{]+|&?[A-Za-z_][\w.]*)\{")
_SLICE_EXPR = re.compile(rf"^{_IDENT}\[[^\]]*:[^\]]*\]$")
_SLICE_LITERAL = re.compile(r"^\[\][^{]+\{(.*)\}$", re.DOTALL)
_CAST = re.compile(rf"^(?:{'|'.join(sorted(_GO_INT_TYPES))})\((.+)\)$")


@dataclass
class _Env:
    nonzero: set[str] = field(default_factory=set)
    nonneg: set[str] = field(default_factory=set)
    nonnil: set[str] = field(default_factory=set)
    # (index, container): 0 <= index < len(container) is *not* implied; only
    # ``index < len(container)``. Non-negativity is tracked separately.
    lt_len: set[tuple[str, str]] = field(default_factory=set)
    # container -> minimum known length (>= 1).
    len_ge: dict[str, int] = field(default_factory=dict)
    consts: dict[str, int] = field(default_factory=dict)
    # name -> (container, delta): name == len(container) + delta.
    len_values: dict[str, tuple[str, int]] = field(default_factory=dict)
    # alias -> root container whose length it shares.
    aliases: dict[str, str] = field(default_factory=dict)
    # Resources that are definitely held/uninitialised on the current path.
    # Entries: ("lock", name), ("file", name, err_name), ("nilmap", name).
    held: set[tuple[str, ...]] = field(default_factory=set)
    # Names known to be slices / arrays / strings (``range`` yields 0-based
    # indices for these, but map *keys* for maps).
    slices: set[str] = field(default_factory=set)

    def copy(self) -> "_Env":
        return _Env(
            nonzero=set(self.nonzero),
            nonneg=set(self.nonneg),
            nonnil=set(self.nonnil),
            lt_len=set(self.lt_len),
            len_ge=dict(self.len_ge),
            consts=dict(self.consts),
            len_values=dict(self.len_values),
            aliases=dict(self.aliases),
            held=set(self.held),
            slices=set(self.slices),
        )

    def merge(self, other: "_Env") -> "_Env":
        return _Env(
            nonzero=self.nonzero & other.nonzero,
            nonneg=self.nonneg & other.nonneg,
            nonnil=self.nonnil & other.nonnil,
            lt_len=self.lt_len & other.lt_len,
            len_ge={
                k: min(v, other.len_ge[k]) for k, v in self.len_ge.items() if k in other.len_ge
            },
            consts={k: v for k, v in self.consts.items() if other.consts.get(k) == v},
            len_values={
                k: v for k, v in self.len_values.items() if other.len_values.get(k) == v
            },
            aliases={k: v for k, v in self.aliases.items() if other.aliases.get(k) == v},
            held=self.held & other.held,
            slices=self.slices & other.slices,
        )

    def kill(self, name: str) -> None:
        """Forget every fact that mentions ``name`` (whole-word match)."""
        name = _norm(name)
        if not name:
            return
        pattern = re.compile(rf"(?<![\w.]){re.escape(name)}(?![\w])")

        def mentions(text: str) -> bool:
            return bool(pattern.search(text)) or text == name or text.startswith(name + ".")

        self.nonzero = {t for t in self.nonzero if not mentions(t)}
        self.nonneg = {t for t in self.nonneg if not mentions(t)}
        self.nonnil = {t for t in self.nonnil if not mentions(t)}
        self.lt_len = {p for p in self.lt_len if not (mentions(p[0]) or mentions(p[1]))}
        self.len_ge = {k: v for k, v in self.len_ge.items() if not mentions(k)}
        self.consts = {k: v for k, v in self.consts.items() if not mentions(k)}
        self.len_values = {
            k: v for k, v in self.len_values.items() if not (mentions(k) or mentions(v[0]))
        }
        self.aliases = {
            k: v for k, v in self.aliases.items() if not (mentions(k) or mentions(v))
        }
        self.held = {
            # A redefined error variable no longer tells us whether the handle
            # is nil, so the ("file", handle, err) entry keeps only the handle.
            (h[0], h[1], "") if len(h) == 3 and mentions(h[2]) else h
            for h in self.held
            if not mentions(h[1])
        }
        self.slices = {t for t in self.slices if not mentions(t)}

    # -- helpers ---------------------------------------------------------

    def root(self, container: str) -> str:
        seen = set()
        while container in self.aliases and container not in seen:
            seen.add(container)
            container = self.aliases[container]
        return container

    def containers_equal_len(self, container: str) -> set[str]:
        root = self.root(container)
        return {root} | {alias for alias in self.aliases if self.root(alias) == root} | {container}

    def add_lt_len(self, index: str, container: str) -> None:
        for name in self.containers_equal_len(container):
            self.lt_len.add((index, name))

    def is_lt_len(self, index: str, container: str) -> bool:
        return (index, container) in self.lt_len or (index, self.root(container)) in self.lt_len

    def min_len(self, container: str) -> int:
        best = 0
        for name in self.containers_equal_len(container):
            best = max(best, self.len_ge.get(name, 0))
        literal = self.consts.get(f"len({container})")
        if literal is not None:
            best = max(best, literal)
        return best

    def set_len_ge(self, container: str, minimum: int) -> None:
        if minimum < 1:
            return
        for name in self.containers_equal_len(container):
            self.len_ge[name] = max(self.len_ge.get(name, 0), minimum)
            self.nonzero.add(f"len({name})")
            self.nonneg.add(f"len({name})")

    def is_sequence(self, container: str) -> bool:
        return any(name in self.slices for name in self.containers_equal_len(container))

    def set_const(self, name: str, value: int) -> None:
        self.consts[name] = value
        if value != 0:
            self.nonzero.add(name)
        if value >= 0:
            self.nonneg.add(name)

    def value_of(self, text: str, constants: dict[str, int]) -> int | None:
        text = _norm(text)
        literal = _parse_int(text)
        if literal is not None:
            return literal
        if text in self.consts:
            return self.consts[text]
        if text in constants:
            return constants[text]
        merged: dict[str, Fraction] = {k: Fraction(v) for k, v in constants.items()}
        merged.update({k: Fraction(v) for k, v in self.consts.items()})
        evaluated = evaluate_constant_expression(text, merged)
        if evaluated is not None and evaluated.denominator == 1:
            return int(evaluated)
        return None

    def copy_facts(self, source: str, target: str) -> None:
        """Copy the facts known about ``source`` to ``target`` (``target := source``)."""
        if source in self.nonzero:
            self.nonzero.add(target)
        if source in self.nonneg:
            self.nonneg.add(target)
        if source in self.nonnil:
            self.nonnil.add(target)
        for index, container in list(self.lt_len):
            if index == source:
                self.lt_len.add((target, container))
        if source in self.consts:
            self.consts[target] = self.consts[source]
        if source in self.len_values:
            self.len_values[target] = self.len_values[source]
        if source in self.len_ge:
            self.len_ge[target] = self.len_ge[source]


# ---------------------------------------------------------------------------
# Condition parsing
# ---------------------------------------------------------------------------

_CMP_OPS = ("==", "!=", "<=", ">=", "<", ">")
_NEGATE_OP = {"==": "!=", "!=": "==", "<": ">=", ">=": "<", ">": "<=", "<=": ">"}
_FLIP_OP = {"==": "==", "!=": "!=", "<": ">", ">": "<", "<=": ">=", ">=": "<="}


def _split_top_level(text: str, operator: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    start = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif depth == 0 and text.startswith(operator, i):
            parts.append(text[start:i])
            i += len(operator)
            start = i
            continue
        i += 1
    parts.append(text[start:])
    return parts


def _strip_parens(text: str) -> str:
    text = text.strip()
    while text.startswith("(") and text.endswith(")"):
        depth = 0
        balanced = True
        for i, ch in enumerate(text):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0 and i != len(text) - 1:
                    balanced = False
                    break
        if not balanced:
            break
        text = text[1:-1].strip()
    return text


def _split_comparison(text: str) -> tuple[str, str, str] | None:
    depth = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif depth == 0:
            for op in _CMP_OPS:
                if text.startswith(op, i):
                    # Avoid matching ``<<`` / ``>>`` / ``<-`` (channel receive).
                    if op in {"<", ">"} and i + 1 < len(text) and text[i + 1] in "<>-=":
                        break
                    if op in {"<", ">"} and i > 0 and text[i - 1] in "<>":
                        break
                    return text[:i].strip(), op, text[i + len(op):].strip()
        i += 1
    return None


class _Facts:
    """Collects facts implied by a boolean condition being true or false."""

    def __init__(self, env: _Env, constants: dict[str, int]):
        self.env = env
        self.constants = constants

    def from_condition(self, text: str, truth: bool) -> _Env:
        """Return a fresh env containing only the facts implied by ``text`` == ``truth``."""
        result = _Env()
        self._collect(text, truth, result)
        return result

    def _collect(self, text: str, truth: bool, out: _Env) -> None:
        text = _strip_parens(text)
        if not text:
            return
        or_parts = _split_top_level(text, "||")
        if len(or_parts) > 1:
            if truth:
                # ``a || b`` true: only facts common to both branches hold.
                envs = [self.from_condition(part, True) for part in or_parts]
                merged = envs[0]
                for env in envs[1:]:
                    merged = merged.merge(env)
                _absorb(out, merged)
            else:
                for part in or_parts:
                    self._collect(part, False, out)
            return
        and_parts = _split_top_level(text, "&&")
        if len(and_parts) > 1:
            if truth:
                for part in and_parts:
                    self._collect(part, True, out)
            else:
                envs = [self.from_condition(part, False) for part in and_parts]
                merged = envs[0]
                for env in envs[1:]:
                    merged = merged.merge(env)
                _absorb(out, merged)
            return
        if text.startswith("!") and not text.startswith("!="):
            self._collect(text[1:], not truth, out)
            return
        comparison = _split_comparison(text)
        if comparison is None:
            return
        left, op, right = comparison
        if not truth:
            op = _NEGATE_OP[op]
        self._comparison(_norm(left), op, _norm(right), out)

    def _comparison(self, left: str, op: str, right: str, out: _Env) -> None:
        left_value = self.env.value_of(left, self.constants)
        right_value = self.env.value_of(right, self.constants)
        if left_value is not None and right_value is None:
            left, right, op, left_value, right_value = right, left, _FLIP_OP[op], right_value, left_value
        if right == "nil":
            if op == "!=":
                out.nonnil.add(left)
            return
        if right_value is not None:
            self._against_constant(left, op, right_value, out)
            return
        # ``x < len(a)`` and friends.
        length = self._length_of(right)
        if length is not None:
            container, delta = length
            if op == "<" and delta <= 0:
                out.add_lt_len(left, container)
                self._mirror_alias_bounds(out, left, container)
            elif op == "<=" and delta <= -1:
                out.add_lt_len(left, container)
                self._mirror_alias_bounds(out, left, container)
            if op in {">", ">="} and delta >= 0:
                out.nonneg.add(left)
                if op == ">" or delta >= 1:
                    out.nonzero.add(left)
            return
        # Relations between two variables: reuse facts known about the right side.
        if op in {"<", "<="}:
            for index, container in self.env.lt_len:
                if index == right:
                    out.add_lt_len(left, container)
            if right in self.env.len_values:
                container, delta = self.env.len_values[right]
                if (op == "<" and delta <= 0) or (op == "<=" and delta <= -1):
                    out.add_lt_len(left, container)
        if op in {">", ">="}:
            if right in self.env.nonneg:
                out.nonneg.add(left)
                if op == ">":
                    out.nonzero.add(left)
            if right in self.env.nonzero and right in self.env.nonneg and op == ">=":
                out.nonzero.add(left)
            if right in self.env.len_values:
                container, delta = self.env.len_values[right]
                if delta >= 0:
                    out.nonneg.add(left)
                    if op == ">" or delta >= 1:
                        out.nonzero.add(left)
        if op == "!=":
            if self.env.consts.get(right) == 0:
                out.nonzero.add(left)
        if op == "==":
            self.env_copy_relation(left, right, out)

    def env_copy_relation(self, left: str, right: str, out: _Env) -> None:
        for name in (right,):
            if name in self.env.nonzero:
                out.nonzero.add(left)
            if name in self.env.nonneg:
                out.nonneg.add(left)
            if name in self.env.nonnil:
                out.nonnil.add(left)
            for index, container in self.env.lt_len:
                if index == name:
                    out.add_lt_len(left, container)

    def _mirror_alias_bounds(self, out: _Env, index: str, container: str) -> None:
        for name in self.env.containers_equal_len(container):
            out.lt_len.add((index, name))

    def _length_of(self, text: str) -> tuple[str, int] | None:
        """Return ``(container, delta)`` when ``text`` == ``len(container) + delta``."""
        match = _LEN_EXPR.match(text)
        if match:
            return match.group(1), 0
        match = _LEN_ARITH.match(text)
        if match:
            value = self.env.value_of(match.group(3), self.constants)
            if value is not None:
                return match.group(1), value if match.group(2) == "+" else -value
        if text in self.env.len_values:
            return self.env.len_values[text]
        return None

    def _against_constant(self, left: str, op: str, value: int, out: _Env) -> None:
        length = self._length_of(left)
        if op == "==":
            out.consts[left] = value
            if value != 0:
                out.nonzero.add(left)
            if value >= 0:
                out.nonneg.add(left)
            if length is not None and value - length[1] >= 1:
                out.set_len_ge(length[0], value - length[1])
        elif op == "!=":
            if value == 0:
                out.nonzero.add(left)
                if length is not None and length[1] <= 0:
                    out.set_len_ge(length[0], 1 - length[1])
        elif op == ">":
            if value >= 0:
                out.nonzero.add(left)
                out.nonneg.add(left)
            elif value == -1:
                out.nonneg.add(left)
            if length is not None and value + 1 - length[1] >= 1:
                out.set_len_ge(length[0], value + 1 - length[1])
        elif op == ">=":
            if value >= 1:
                out.nonzero.add(left)
                out.nonneg.add(left)
            elif value == 0:
                out.nonneg.add(left)
            if length is not None and value - length[1] >= 1:
                out.set_len_ge(length[0], value - length[1])
        elif op == "<":
            if value <= 0:
                out.nonzero.add(left)
        elif op == "<=":
            if value <= -1:
                out.nonzero.add(left)


def _is_whole_call(text: str) -> bool:
    """True when ``text`` is a single call whose argument list spans to the end."""
    start = text.find("(")
    if start < 0 or not text.endswith(")"):
        return False
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i == len(text) - 1
    return False


def _strip_borrowing_calls(value: str) -> str:
    """Blank plain handle arguments of read/write helpers that do not take ownership."""
    result = value
    for match in list(_BORROWING_CALLS.finditer(value))[::-1]:
        start = match.end()
        depth = 1
        i = start
        while i < len(value) and depth > 0:
            if value[i] in "([{":
                depth += 1
            elif value[i] in ")]}":
                depth -= 1
            i += 1
        args = value[start : i - 1]
        kept = [
            "" if re.fullmatch(r"\s*&?[A-Za-z_]\w*\s*", arg) else arg
            for arg in _split_top_level(args, ",")
        ]
        result = result[:start] + ",".join(kept) + result[i - 1 :]
    return result


def _join_termination(*kinds: str) -> str:
    """Termination kind of a join where every branch left the block."""
    for kind in ("fallthrough", "continue", "break"):
        if kind in kinds:
            return kind
    return kinds[0] if kinds else "return"


def _contains_kind(statements: tuple[tree_sitter_extract.Statement, ...], kind: str) -> bool:
    for statement in statements:
        if statement.kind == kind:
            return True
        for group in (statement.init, statement.body, statement.orelse, statement.post):
            if _contains_kind(group, kind):
                return True
    return False


def _absorb(target: _Env, source: _Env) -> None:
    target.nonzero |= source.nonzero
    target.nonneg |= source.nonneg
    target.nonnil |= source.nonnil
    target.lt_len |= source.lt_len
    for k, v in source.len_ge.items():
        target.len_ge[k] = max(target.len_ge.get(k, 0), v)
    target.consts.update(source.consts)
    target.len_values.update(source.len_values)
    target.aliases.update(source.aliases)
    target.held |= source.held


# ---------------------------------------------------------------------------
# Public result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PathFacts:
    """Facts that hold on every path reaching a particular expression."""

    nonzero: frozenset[str] = frozenset()
    nonneg: frozenset[str] = frozenset()
    nonnil: frozenset[str] = frozenset()
    # ``(index, container)`` pairs with ``index < len(container)``.
    lt_len: frozenset[tuple[str, str]] = frozenset()
    # container -> minimum length.
    len_ge: dict[str, int] = field(default_factory=dict)
    consts: dict[str, int] = field(default_factory=dict)

    def bounded_indices(self, index_accesses: tuple[tuple[str, str], ...]) -> set[str]:
        """Return index names proven within ``[0, len(container))`` for *every* access.

        ``index_accesses`` is ``ExpressionSafety.index_accesses`` (``(container,
        index)`` pairs). An index is only reported when each container it is
        used with is covered, so a shared index variable never suppresses an
        unguarded access.
        """
        by_index: dict[str, set[str]] = {}
        for container, index in index_accesses:
            by_index.setdefault(index, set()).add(container)
        guarded: set[str] = set()
        for index, containers in by_index.items():
            if index not in self.nonneg and index not in self.consts:
                continue
            if index in self.consts and self.consts[index] < 0:
                continue
            if all(self._index_in_range(index, container) for container in containers):
                guarded.add(index)
        return guarded

    def _index_in_range(self, index: str, container: str) -> bool:
        if (index, container) in self.lt_len:
            return True
        value = self.consts.get(index)
        if value is not None and 0 <= value < self.len_ge.get(container, 0):
            return True
        return False

    def merge(self, other: "PathFacts") -> "PathFacts":
        return PathFacts(
            nonzero=self.nonzero & other.nonzero,
            nonneg=self.nonneg & other.nonneg,
            nonnil=self.nonnil & other.nonnil,
            lt_len=self.lt_len & other.lt_len,
            len_ge={k: min(v, other.len_ge[k]) for k, v in self.len_ge.items() if k in other.len_ge},
            consts={k: v for k, v in self.consts.items() if other.consts.get(k) == v},
        )


def _freeze(env: _Env) -> PathFacts:
    nonzero = set(env.nonzero)
    nonneg = set(env.nonneg)
    for name, value in env.consts.items():
        if value != 0:
            nonzero.add(name)
        if value >= 0:
            nonneg.add(name)
    for name, minimum in env.len_ge.items():
        if minimum >= 1:
            nonzero.add(f"len({name})")
    for name, (container, delta) in env.len_values.items():
        if env.min_len(container) + delta >= 1:
            nonzero.add(name)
            nonneg.add(name)
        elif delta >= 0:
            nonneg.add(name)
    lt_len = set(env.lt_len)
    for index, container in list(env.lt_len):
        for name in env.containers_equal_len(container):
            lt_len.add((index, name))
    return PathFacts(
        nonzero=frozenset(nonzero),
        nonneg=frozenset(nonneg),
        nonnil=frozenset(env.nonnil),
        lt_len=frozenset(lt_len),
        len_ge=dict(env.len_ge),
        consts=dict(env.consts),
    )


@dataclass(frozen=True)
class DataflowIssue:
    """A bug found by the dataflow layer alone (new categories)."""

    category: str  # "nil_map_write" | "lock_held_at_return" | "double_lock" | "resource_leak"
    subject: str
    statement: str
    offset: int


@dataclass(frozen=True)
class FunctionDataflow:
    """Dataflow facts for one function body."""

    # Folded local ``const`` values (and package constants passed in).
    constants: dict[str, int]
    # Normalised return-expression text -> facts holding at every such return.
    return_facts: dict[str, PathFacts]
    # Facts holding at the fall-through end of the body (no explicit return).
    issues: tuple[DataflowIssue, ...] = ()

    def facts_for_expression(self, expression: str) -> PathFacts | None:
        """Return the facts at the return(s) of ``expression`` or ``None`` when unknown."""
        key = _norm(expression)
        if key in self.return_facts:
            return self.return_facts[key]
        if not key:
            return None
        # Sub-expression lookup: the key must appear as a whole operand of the
        # return expression, not as a substring of a longer identifier.
        pattern = re.compile(rf"(?<![\w.]){re.escape(key)}(?![\w(])")
        candidates = [
            facts for text, facts in self.return_facts.items() if pattern.search(text)
        ]
        if not candidates:
            return None
        merged = candidates[0]
        for facts in candidates[1:]:
            merged = merged.merge(facts)
        return merged


# ---------------------------------------------------------------------------
# Walker
# ---------------------------------------------------------------------------


class _Walker:
    def __init__(
        self,
        tree: tree_sitter_extract.StatementTree,
        constants: dict[str, int],
        param_names: set[str],
        body: str,
    ) -> None:
        self.tree = tree
        self.constants = dict(constants)
        self.param_names = param_names
        self.body = body
        self.unreliable = set(tree.closure_assigned) | set(tree.address_taken)
        self.return_facts: dict[str, list[_Env]] = {}
        self.issues: list[DataflowIssue] = []
        # Environments carried by ``break`` to the innermost enclosing switch /
        # loop (one list per open construct).
        self.break_targets: list[list[_Env]] = []

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _length_bounded(name: str, env: _Env) -> bool:
        """``name`` is at most a sequence length, so small arithmetic cannot overflow."""
        return name in env.len_values or any(index == name for index, _ in env.lt_len)

    def _reliable(self, name: str) -> bool:
        root = name.split(".")[0].lstrip("&*")
        return root not in self.unreliable

    def _facts(self, env: _Env) -> _Facts:
        return _Facts(env, self.constants)

    def _apply_condition(self, env: _Env, condition: str, truth: bool) -> _Env:
        result = env.copy()
        derived = self._facts(env).from_condition(condition, truth)
        self._filter_unreliable(derived)
        _absorb(result, derived)
        return result

    def _filter_unreliable(self, env: _Env) -> None:
        env.nonzero = {t for t in env.nonzero if self._reliable(t)}
        env.nonneg = {t for t in env.nonneg if self._reliable(t)}
        env.nonnil = {t for t in env.nonnil if self._reliable(t)}
        env.lt_len = {p for p in env.lt_len if self._reliable(p[0]) and self._reliable(p[1])}
        env.len_ge = {k: v for k, v in env.len_ge.items() if self._reliable(k)}
        env.consts = {k: v for k, v in env.consts.items() if self._reliable(k)}
        env.len_values = {
            k: v for k, v in env.len_values.items() if self._reliable(k) and self._reliable(v[0])
        }
        env.aliases = {k: v for k, v in env.aliases.items() if self._reliable(k) and self._reliable(v)}

    @staticmethod
    def _assigned_names(statements: tuple[tree_sitter_extract.Statement, ...]) -> set[str]:
        names: set[str] = set()
        for statement in statements:
            if statement.kind in {"define", "assign", "inc", "dec", "var", "const"}:
                for target in statement.targets:
                    names.add(_norm(target))
                    names.add(_norm(target).split("[")[0].split(".")[0].lstrip("*"))
            if statement.kind == "range":
                for target in statement.targets:
                    names.add(_norm(target))
            if statement.kind == "closure":
                names.update(statement.targets)
            for group in (statement.init, statement.body, statement.orelse, statement.post):
                names |= _Walker._assigned_names(group)
        names.discard("_")
        return names

    @staticmethod
    def _keep_nil_maps(loop_env: _Env, outer: _Env, statements: tuple[tree_sitter_extract.Statement, ...]) -> None:
        """Re-establish ``("nilmap", m)`` in ``loop_env`` when the loop body only
        writes ``m[k] = v`` (which never initialises ``m``) and never assigns
        ``m`` itself."""
        whole: set[str] = set()

        def collect(group: tuple[tree_sitter_extract.Statement, ...]) -> None:
            for statement in group:
                if statement.kind in {"define", "assign", "var", "range", "closure"}:
                    for target in statement.targets:
                        normalized = _norm(target).lstrip("*")
                        if re.fullmatch(_IDENT, normalized):
                            whole.add(normalized)
                for nested in (statement.init, statement.body, statement.orelse, statement.post):
                    collect(nested)

        collect(statements)
        loop_env.held |= {h for h in outer.held if h[0] == "nilmap" and h[1] not in whole}

    # -- statement walk --------------------------------------------------

    def walk(
        self, statements: tuple[tree_sitter_extract.Statement, ...], env: _Env
    ) -> tuple[_Env, str]:
        """Walk ``statements`` from ``env``; return ``(env_after, terminated)``.

        ``terminated`` is ``""`` when control falls off the end, otherwise the
        kind of statement that left the block (``"return"``, ``"terminate"``,
        ``"break"``, ``"continue"``, ``"fallthrough"``).
        """
        for statement in statements:
            env, terminated = self.statement(statement, env)
            if terminated:
                return env, terminated
        return env, ""

    def statement(self, statement: tree_sitter_extract.Statement, env: _Env) -> tuple[_Env, str]:
        kind = statement.kind
        if kind == "return":
            self._on_return(statement, env)
            return env, kind
        if kind == "terminate":
            return env, kind
        if kind == "break":
            if self.break_targets:
                self.break_targets[-1].append(env.copy())
            return env, kind
        if kind in {"continue", "fallthrough"}:
            return env, kind
        if kind == "if":
            return self._if(statement, env)
        if kind == "for":
            return self._for(statement, env), ""
        if kind == "range":
            return self._range(statement, env), ""
        if kind == "switch":
            return self._switch(statement, env)
        if kind == "block":
            inner, terminated = self.walk(statement.body, env.copy())
            return inner, terminated
        if kind in {"define", "assign"}:
            self._assign(statement, env)
            return env, ""
        if kind in {"inc", "dec"}:
            for target in statement.targets:
                name = _norm(target)
                keep_nonneg = kind == "inc" and name in env.nonneg and self._length_bounded(name, env)
                env.kill(name)
                if keep_nonneg:
                    env.nonneg.add(name)
            return env, ""
        if kind == "const":
            declarations = [
                (name, value) for name, value in zip(statement.targets, statement.values)
            ]
            # Local constants are lexically scoped: they live in the path
            # environment only, so a same-named parameter used after the
            # enclosing block is not mistaken for the constant.
            base = dict(self.constants)
            base.update(env.consts)
            folded = fold_constants(declarations, base)
            for name, _value in declarations:
                env.kill(name)
                if name in folded:
                    env.set_const(name, folded[name])
            return env, ""
        if kind == "var":
            self._var(statement, env)
            return env, ""
        if kind == "defer":
            for value in statement.values:
                self._release(value, env, deferred=True)
            return env, ""
        if kind == "closure":
            for value in statement.values:
                if re.search(r"\.(Unlock|RUnlock|Close)\s*\(", value):
                    for match in re.finditer(r"(&?[A-Za-z_][\w.]*)\.(Unlock|RUnlock|Close)\s*\(", value):
                        env.held = {
                            h for h in env.held if h[1] != match.group(1).lstrip("&")
                        }
            for name in statement.targets:
                env.kill(name)
            return env, ""
        if kind == "expr":
            for value in statement.values:
                self._expression(value, env)
            return env, ""
        return env, ""

    def _on_return(self, statement: tree_sitter_extract.Statement, env: _Env) -> None:
        keys = set()
        joined = _norm(", ".join(statement.values))
        if joined:
            keys.add(joined)
        for value in statement.values:
            keys.add(_norm(value))
        for key in keys:
            self.return_facts.setdefault(key, []).append(env.copy())
        self._check_resources_at_exit(statement, env, statement.values)

    def _check_resources_at_exit(
        self, statement: tree_sitter_extract.Statement, env: _Env, values: tuple[str, ...]
    ) -> None:
        returned = " ".join(values)
        deferred = {h[1] for h in env.held if h[0] == "deferred"}
        for held in sorted(env.held):
            if held[1] in deferred:
                continue
            if held[0] == "lock":
                self.issues.append(
                    DataflowIssue("lock_held_at_return", held[1], statement.text, statement.start)
                )
            elif held[0] == "file":
                name, err_name = held[1], held[2]
                if err_name and err_name in env.nonnil:
                    # ``if err != nil { return err }`` right after the open call:
                    # the handle is nil on this path.
                    continue
                if re.search(rf"(?<![\w.]){re.escape(name)}(?![\w])", returned):
                    continue
                self.issues.append(
                    DataflowIssue("resource_leak", name, statement.text, statement.start)
                )

    def _if(self, statement: tree_sitter_extract.Statement, env: _Env) -> tuple[_Env, str]:
        base = env.copy()
        if statement.init:
            base, _ = self.walk(statement.init, base)
        then_env = self._apply_condition(base, statement.condition, True)
        then_env, then_terminated = self.walk(statement.body, then_env)
        else_env = self._apply_condition(base, statement.condition, False)
        else_terminated = ""
        if statement.orelse:
            else_env, else_terminated = self.walk(statement.orelse, else_env)
        if then_terminated and else_terminated:
            return then_env.merge(else_env), _join_termination(then_terminated, else_terminated)
        if then_terminated:
            result = else_env
        elif else_terminated:
            result = then_env
        else:
            result = then_env.merge(else_env)
        if statement.init:
            for name in self._assigned_names(statement.init):
                # ``if v, ok := ...; ok {`` scopes ``v``/``ok`` to the statement.
                result.kill(name)
        return result, ""

    def _for(self, statement: tree_sitter_extract.Statement, env: _Env) -> _Env:
        outer = env.copy()
        if statement.init:
            outer, _ = self.walk(statement.init, outer)
        body_assigned = self._assigned_names(statement.body)
        post_assigned = self._assigned_names(statement.post)
        assigned = body_assigned | post_assigned
        loop_env = outer.copy()
        # A counter that only moves monotonically in the update clause keeps
        # the one-sided bound established by its initializer: ``i--`` keeps
        # ``i < len(a)`` from ``i := len(a) - 1``; ``i++`` keeps ``i >= 0``.
        decreasing = {
            _norm(t)
            for post in statement.post
            if post.kind == "dec" or (post.kind == "assign" and post.operator == "-=")
            for t in post.targets
        } - body_assigned
        increasing = {
            _norm(t)
            for post in statement.post
            if post.kind == "inc" or (post.kind == "assign" and post.operator == "+=")
            for t in post.targets
        } - body_assigned
        kept_lt_len = {p for p in outer.lt_len if p[0] in decreasing and p[1] not in assigned}
        kept_nonneg = {n for n in outer.nonneg if n in increasing}
        for name in assigned:
            loop_env.kill(name)
        loop_env.lt_len |= kept_lt_len
        loop_env.nonneg |= kept_nonneg
        self._keep_nil_maps(loop_env, outer, statement.body + statement.post)
        body_env = self._apply_condition(loop_env, statement.condition, True) if statement.condition else loop_env
        self.break_targets.append([])
        body_end, terminated = self.walk(statement.body, body_env)
        self.break_targets.pop()
        after = self._loop_exit(outer, body_end, terminated, statement)
        for name in self._assigned_names(statement.init):
            after.kill(name)
        return after

    def _loop_exit(
        self,
        before: _Env,
        body_end: _Env,
        terminated: str,
        statement: tree_sitter_extract.Statement,
    ) -> _Env:
        """State after a loop: zero iterations (``before``) or the end of some
        iteration (``body_end`` after the update clause), merged by intersection.

        A ``break`` (or a body that always terminates) can leave the loop from
        an arbitrary point, so only the conservative "kill everything assigned"
        state is kept in that case.
        """
        assigned = self._assigned_names(statement.body) | self._assigned_names(statement.post)
        assigned |= {_norm(t) for t in statement.targets}
        if terminated or self._has_break(statement.body):
            after = before.copy()
            for name in assigned:
                after.kill(name)
            return after
        iterated = body_end
        if statement.post:
            iterated, _ = self.walk(statement.post, body_end.copy())
        after = before.merge(iterated)
        if statement.kind == "for" and statement.condition:
            after = self._apply_condition(after, statement.condition, False)
        return after

    def _has_break(self, statements: tuple[tree_sitter_extract.Statement, ...]) -> bool:
        """True when a ``break`` / ``continue`` / ``goto`` appears anywhere in
        ``statements`` (nested constructs included, conservatively)."""
        for statement in statements:
            if statement.kind in {"terminate", "break", "continue", "goto"}:
                return True
            if statement.kind == "closure":
                continue
            if (
                self._has_break(statement.init)
                or self._has_break(statement.body)
                or self._has_break(statement.orelse)
                or self._has_break(statement.post)
            ):
                return True
        return False

    def _range(self, statement: tree_sitter_extract.Statement, env: _Env) -> _Env:
        assigned = self._assigned_names(statement.body) | {_norm(t) for t in statement.targets}
        loop_env = env.copy()
        for name in assigned:
            loop_env.kill(name)
        self._keep_nil_maps(loop_env, env, statement.body)
        iterable = _norm(statement.values[0]) if statement.values else ""
        if (
            statement.targets
            and iterable
            and re.fullmatch(_IDENT, iterable)
            and env.is_sequence(iterable)
        ):
            index = _norm(statement.targets[0])
            if index != "_" and self._reliable(index) and self._reliable(iterable):
                loop_env.nonneg.add(index)
                loop_env.add_lt_len(index, iterable)
                if len(statement.targets) >= 2:
                    loop_env.kill(_norm(statement.targets[1]))
        self.break_targets.append([])
        body_end, terminated = self.walk(statement.body, loop_env)
        self.break_targets.pop()
        return self._loop_exit(env, body_end, terminated, statement)

    def _switch(self, statement: tree_sitter_extract.Statement, env: _Env) -> tuple[_Env, str]:
        base = env.copy()
        if statement.init:
            base, _ = self.walk(statement.init, base)
        outgoing: list[_Env] = []
        has_default = False
        previous_conditions: list[str] = []
        tag = _norm(statement.condition)
        case_values: list[str] = []
        carried: _Env | None = None
        exits: list[str] = []
        self.break_targets.append([])
        for case in statement.body:
            case_env = base.copy()
            if case.kind == "default":
                has_default = True
                if statement.has_tag and tag:
                    for value in case_values:
                        case_env = self._apply_condition(case_env, f"{tag} != {value}", True)
                elif not statement.has_tag:
                    for condition in previous_conditions:
                        case_env = self._apply_condition(case_env, condition, False)
            elif case.kind == "case":
                if statement.has_tag and tag:
                    if len(case.values) == 1:
                        case_env = self._apply_condition(case_env, f"{tag} == {case.values[0]}", True)
                    elif case.values and all(
                        (v := base.value_of(value, self.constants)) is not None and v != 0
                        for value in case.values
                    ):
                        case_env = self._apply_condition(case_env, f"{tag} != 0", True)
                    case_values.extend(case.values)
                elif not statement.has_tag and case.values:
                    for condition in previous_conditions:
                        case_env = self._apply_condition(case_env, condition, False)
                    condition = " || ".join(case.values)
                    case_env = self._apply_condition(case_env, condition, True)
                    previous_conditions.append(condition)
            if carried is not None:
                # ``fallthrough`` from the previous case enters this body
                # without this case's selector guard.
                case_env = case_env.merge(carried)
                carried = None
            case_env, terminated = self.walk(case.body, case_env)
            if terminated == "fallthrough":
                carried = case_env
            elif not terminated:
                outgoing.append(case_env)
            else:
                exits.append(terminated)
        if carried is not None:
            outgoing.append(carried)
        outgoing.extend(self.break_targets.pop())
        if not has_default:
            outgoing.append(base.copy())
        if not outgoing:
            return base, _join_termination(*exits)
        merged = outgoing[0]
        for other in outgoing[1:]:
            merged = merged.merge(other)
        if statement.init:
            for name in self._assigned_names(statement.init):
                merged.kill(name)
        return merged, ""

    # -- assignments -----------------------------------------------------

    def _var(self, statement: tree_sitter_extract.Statement, env: _Env) -> None:
        types = statement.operator.split("|") if statement.operator else []
        for index, name in enumerate(statement.targets):
            value = statement.values[index] if index < len(statement.values) else ""
            type_text = _norm(types[index]) if index < len(types) else ""
            env.kill(name)
            if value:
                self._define(name, value, env)
                continue
            if not self._reliable(name):
                continue
            if type_text.startswith("map["):
                env.held.add(("nilmap", name))
            elif type_text in _GO_INT_TYPES:
                env.set_const(name, 0)
            elif type_text.startswith("[") or type_text == "string":
                env.slices.add(name)
                fixed = re.match(r"^\[(\w+)\]", type_text)
                if fixed:
                    size = env.value_of(fixed.group(1), self.constants)
                    if size is not None and size >= 1:
                        env.set_len_ge(name, size)

    def _assign(self, statement: tree_sitter_extract.Statement, env: _Env) -> None:
        targets = [_norm(t) for t in statement.targets]
        values = list(statement.values)
        if statement.operator not in {"=", ":="}:
            for target in targets:
                keep_nonneg = (
                    target in env.nonneg
                    and len(values) == 1
                    and (
                        statement.operator in {">>=", "&="}
                        and self._nonneg_value(values[0], env)
                        or statement.operator in {"+=", "*=", "<<=", "|=", "^="}
                        and self._length_bounded(target, env)
                        and env.value_of(values[0], self.constants) is not None
                        and env.value_of(values[0], self.constants) >= 0
                    )
                )
                env.kill(target)
                if keep_nonneg:
                    env.nonneg.add(target)
            return
        for target in targets:
            if target == "_":
                continue
            # ``m[k] = v`` on a nil map panics.
            index_match = re.match(rf"^({_IDENT})\[", target)
            if index_match and ("nilmap", index_match.group(1)) in env.held:
                self.issues.append(
                    DataflowIssue("nil_map_write", index_match.group(1), statement.text, statement.start)
                )
        # Values are evaluated before any target is written.
        pending: list[tuple[str, str]] = []
        if len(targets) == len(values):
            pending = list(zip(targets, values))
        for target in targets:
            if target != "_":
                env.kill(target)
                if not re.fullmatch(_IDENT, target):
                    root = target.split("[")[0].split(".")[0].lstrip("*")
                    if target.startswith("*"):
                        env.kill(root)
        if len(targets) >= 2 and len(values) == 1:
            self._open_resource(targets, values[0], env)
        if len(targets) >= 1 and len(values) == 1 and len(targets) != len(values):
            self._escape(values[0], env)
            return
        for target, value in pending:
            if target == "_" or not re.fullmatch(_IDENT, target):
                self._escape(value, env)
                continue
            self._define(target, value, env)

    def _open_resource(self, targets: list[str], value: str, env: _Env) -> None:
        if not _OPEN_CALLS.match(value.strip()):
            return
        *handles, err = targets
        err = err if re.fullmatch(_IDENT, err) and err != "_" else ""
        for handle in handles:
            if handle == "_" or not re.fullmatch(_IDENT, handle) or not self._reliable(handle):
                continue
            env.held.add(("file", handle, err))

    def _escape(self, value: str, env: _Env) -> None:
        """Forget open handles that are passed on / stored (ownership transfer).

        A bare mention of the handle that is not a method call on it
        (``process(f)``, ``s.file = f``, ``return f``) means the current
        function may no longer own the resource, so no leak is reported.
        """
        stripped = _strip_borrowing_calls(value)
        for held in list(env.held):
            if held[0] == "file" and re.search(
                rf"(?<![\w.]){re.escape(held[1])}(?![\w])(?!\s*\.)", stripped
            ):
                env.held.discard(held)

    @staticmethod
    def _nonneg_value(value: str, env: _Env) -> bool:
        text = _norm(value)
        literal = _parse_int(text)
        if literal is not None:
            return literal >= 0
        return text in env.nonneg or text in env.consts and env.consts[text] >= 0

    def _define(self, target: str, value: str, env: _Env) -> None:
        text = _norm(value)
        self._escape(value, env)
        if not self._reliable(target):
            return
        constant = env.value_of(text, self.constants)
        if constant is not None:
            env.set_const(target, constant)
            return
        if _NONNEG_CALLS.match(text) and _is_whole_call(text):
            env.nonneg.add(target)
            return
        cast = _CAST.match(text)
        if cast:
            inner_value = env.value_of(cast.group(1), self.constants)
            if inner_value is not None:
                env.set_const(target, inner_value)
            elif text.split("(", 1)[0] in GO_UNSIGNED_TYPES:
                env.nonneg.add(target)
            # A conversion of a non-constant may wrap or change sign, so no other
            # fact survives it.
            return
        if re.fullmatch(_IDENT, text) and text != "nil":
            env.copy_facts(text, target)
            env.aliases[target] = env.root(text)
            if env.is_sequence(text):
                env.slices.add(target)
            return
        if text.startswith("[") or _SLICE_EXPR.match(text) or text.startswith("make(["):
            env.slices.add(target)
        if text.startswith("&"):
            env.nonnil.add(target)
            return
        if _COMPOSITE.match(text) or text.startswith(("make(", "new(")):
            env.nonnil.add(target)
            make_len = _MAKE_LEN.match(text)
            if make_len:
                env.aliases[target] = env.root(make_len.group(1))
                return
            make_size = _MAKE_SIZE.match(text)
            if make_size:
                size = env.value_of(make_size.group(1), self.constants)
                if size is not None and size >= 1:
                    env.set_len_ge(target, size)
                elif make_size.group(1) in env.nonzero and make_size.group(1) in env.nonneg:
                    env.set_len_ge(target, 1)
                elif make_size.group(1) in env.len_values:
                    container, delta = env.len_values[make_size.group(1)]
                    if delta == 0:
                        env.aliases[target] = env.root(container)
                return
            grow = _MAKE_GROW.match(text)
            if grow:
                # ``xs = make([]T, n+k)`` with ``n >= 0`` and ``k >= 1``: ``xs[n]`` is valid.
                index, delta = grow.groups()
                delta_value = env.value_of(delta, self.constants)
                if (
                    delta_value is not None
                    and delta_value >= 1
                    and (index in env.nonneg or env.consts.get(index, -1) >= 0)
                ):
                    env.set_len_ge(target, 1)
                    env.add_lt_len(index, target)
                return
            literal = _SLICE_LITERAL.match(value.strip())
            if literal:
                elements = [part for part in _split_top_level(literal.group(1), ",") if part.strip()]
                if elements:
                    env.set_len_ge(target, len(elements))
            return
        length = _Facts(env, self.constants)._length_of(text)
        if length is not None:
            container, delta = length
            if self._reliable(container):
                env.len_values[target] = (container, delta)
                if delta >= 0:
                    env.nonneg.add(target)
                if delta <= -1:
                    env.add_lt_len(target, container)
                    if env.min_len(container) + delta >= 0:
                        env.nonneg.add(target)
            return
        div = _LEN_DIV.match(text)
        if div:
            divisor = env.value_of(div.group(2), self.constants)
            if divisor is not None and divisor >= 1:
                env.nonneg.add(target)
                if divisor >= 2 or ">>" in text:
                    if env.min_len(div.group(1)) >= 1:
                        env.add_lt_len(target, div.group(1))
            return
        paren = _PAREN_LEN_ARITH.match(text)
        if paren:
            container, sign, delta_text, divisor_text = paren.groups()
            delta = env.value_of(delta_text, self.constants)
            divisor = env.value_of(divisor_text, self.constants)
            if delta is not None and divisor is not None and divisor >= 1:
                if sign == "-":
                    delta = -delta
                if delta <= -1:
                    env.add_lt_len(target, container)
                    if env.min_len(container) + delta >= 0:
                        env.nonneg.add(target)
                elif delta == 0 and divisor >= 2 and env.min_len(container) >= 1:
                    env.add_lt_len(target, container)
                    env.nonneg.add(target)
                elif delta >= 0:
                    env.nonneg.add(target)
            return
        mod_len = _MOD_LEN.match(text)
        if mod_len:
            dividend, container = mod_len.groups()
            # ``x % len(xs)`` panics when ``xs`` is empty, so the index is only
            # in range once the container is known non-empty on this path.
            if (dividend in env.nonneg or env.consts.get(dividend, -1) >= 0) and (
                env.min_len(container) >= 1 or f"len({container})" in env.nonzero
            ):
                env.nonneg.add(target)
                env.add_lt_len(target, container)
            return
        mod_const = _MOD_CONST.match(text)
        if mod_const:
            dividend, modulus = mod_const.groups()
            modulus_value = env.value_of(modulus, self.constants)
            if (dividend in env.nonneg or env.consts.get(dividend, -1) >= 0) and (
                modulus_value is None or modulus_value > 0
            ):
                env.nonneg.add(target)
            return
        bit_and = _BIT_AND.match(text)
        if bit_and:
            mask = env.value_of(bit_and.group(2), self.constants)
            if mask is not None and mask >= 0:
                env.nonneg.add(target)
            return
        arith = _SIMPLE_ARITH.match(text)
        if arith:
            left, op, right = arith.groups()
            right_value = env.value_of(right, self.constants)
            left_nonneg = left in env.nonneg or env.consts.get(left, -1) >= 0
            # ``+`` / ``*`` keep the sign only when the result provably cannot
            # wrap: the left operand is bounded by a sequence length (or is a
            # constant) and the right operand is a non-negative constant.
            if (
                op in {"+", "*"}
                and left_nonneg
                and right_value is not None
                and right_value >= 0
                and (left in env.consts or self._length_bounded(left, env))
            ):
                env.nonneg.add(target)
                if op == "+" and (
                    left in env.nonzero or (right_value is not None and right_value >= 1) or right in env.nonzero
                ):
                    env.nonzero.add(target)
                if op == "*" and left in env.nonzero and (
                    (right_value is not None and right_value >= 1) or right in env.nonzero
                ):
                    env.nonzero.add(target)
            elif op == "-" and right_value is not None and right_value >= 1 and left_nonneg and left in env.nonzero:
                if left in env.len_values:
                    container, delta = env.len_values[left]
                    env.len_values[target] = (container, delta - right_value)
                    env.add_lt_len(target, container)
                if right_value == 1:
                    env.nonneg.add(target)
                    for index, container in list(env.lt_len):
                        if index == left:
                            env.add_lt_len(target, container)
            elif op == "/" and left_nonneg and right_value is not None and right_value >= 1:
                env.nonneg.add(target)
                if right_value >= 2:
                    for index, container in list(env.lt_len):
                        if index == left:
                            env.add_lt_len(target, container)
            return

    # -- expressions / resources ----------------------------------------

    def _expression(self, value: str, env: _Env) -> None:
        match = re.match(r"^(&?[A-Za-z_][\w.]*)\.(Lock|RLock|Unlock|RUnlock|Close)\s*\(\s*\)$", value.strip())
        if match:
            subject, method = match.group(1).lstrip("&"), match.group(2)
            if not self._reliable(subject):
                return
            if method in _LOCK_METHODS:
                if ("lock", subject) in env.held and method == "Lock":
                    self.issues.append(
                        DataflowIssue("double_lock", subject, value.strip(), 0)
                    )
                env.held.add(("lock", subject))
            else:
                self._release(value, env, deferred=False)
            return
        self._escape(value, env)

    def _release(self, value: str, env: _Env, *, deferred: bool) -> None:
        match = re.match(r"^(&?[A-Za-z_][\w.]*)\.(Unlock|RUnlock|Close)\s*\(", value.strip())
        if not match:
            if deferred:
                # ``defer func() { ... }()`` / ``defer cleanup(f)`` — treat any
                # resource mentioned as released to stay conservative.
                for held in list(env.held):
                    if held[0] != "nilmap" and re.search(rf"(?<![\w.]){re.escape(held[1])}(?![\w])", value):
                        env.held.discard(held)
            else:
                self._escape(value, env)
            return
        subject = match.group(1).lstrip("&")
        if deferred:
            env.held.add(("deferred", subject))
        else:
            env.held = {h for h in env.held if h[1] != subject}

    # -- entry -----------------------------------------------------------

    def run(self, seed: _Env | None = None) -> FunctionDataflow:
        env = seed.copy() if seed is not None else _Env()
        final_env, terminated = self.walk(self.tree.statements, env)
        if not terminated:
            # Fall-through end of body (procedure without a trailing return).
            self._check_resources_at_exit(
                tree_sitter_extract.Statement(kind="end", text="", start=len(self.body)),
                final_env,
                (),
            )
        return_facts: dict[str, PathFacts] = {}
        for key, envs in self.return_facts.items():
            merged = envs[0]
            for other in envs[1:]:
                merged = merged.merge(other)
            return_facts[key] = _freeze(merged)
        return FunctionDataflow(
            constants=dict(self.constants),
            return_facts=return_facts,
            issues=tuple(self.issues),
        )


def analyze_function(
    body: str,
    language: str,
    *,
    constants: dict[str, int] | None = None,
    param_names: set[str] | None = None,
    nonneg_names: set[str] | None = None,
    nonzero_names: set[str] | None = None,
    sequence_names: set[str] | None = None,
) -> FunctionDataflow | None:
    """Return function-local dataflow facts for ``body`` or ``None`` to fall back.

    ``constants`` are package-level constants already resolved by
    :mod:`agent.semantic_safety`; local ``const`` declarations are folded on
    top of them. ``nonneg_names`` (unsigned parameters / variables) and
    ``nonzero_names`` (package-level facts such as a non-empty global slice's
    ``len(xs)``) seed the entry state. Only Go bodies are analysed for now.
    """
    tree = tree_sitter_extract.extract_statements(body, language)
    if tree is None or _contains_kind(tree.statements, "goto"):
        return None
    walker = _Walker(tree, constants or {}, param_names or set(), body)
    seed = _Env()
    seed.nonneg |= {_norm(n) for n in nonneg_names or ()}
    seed.nonzero |= {_norm(n) for n in nonzero_names or ()}
    seed.slices |= {_norm(n) for n in sequence_names or ()}
    try:
        return walker.run(seed)
    except RecursionError:
        return None
