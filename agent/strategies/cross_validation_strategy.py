"""Cross-validate Mumei specifications (.mm) against implementation code.

Detects semantic gaps where the specification is stronger, weaker, or
contradicts the implementation.  Also detects spec drift from proof
certificate content-hash changes and computes coverage of spec atoms
against implementation functions.

Typical usage::

    from agent.strategies.cross_validation_strategy import CrossValidator

    validator = CrossValidator()
    report = validator.validate_spec_vs_impl(
        spec_path="contracts.mm",
        impl_path="src/lib.rs",
        language="rust",
    )
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agent.strategies.cross_validation_strategy_helpers import (
    _ATOM_DEF_RE,
    _ENSURES_RE,
    _GO_FUNC_RE,
    _PYTHON_FUNC_RE,
    _REQUIRES_RE,
    _RUST_FUNC_RE,
    _TS_ARROW_RE,
    _TS_FUNC_RE,
    _canonical_language,
    _canonical_symbol,
    _extract_function_body,
    _extract_functions,
    _extract_spec_atoms,
)


def _is_short_native_or_wrapper_body(body: str) -> bool:
    """Return True when ``body`` is a short call/return wrapper without local logic.

    Constant-time helpers, forwarded calls, and other native wrappers often
    have non-trivial safety ``requires`` (e.g. slice-length bounds) while the
    body itself is just a single statement. Such cases should not be reported
    as "spec stronger than implementation".
    """
    text = body.strip()
    if not text:
        return True
    # Bodies with control flow are doing real validation/processing.
    if re.search(r"\b(if|for|while|switch|range)\b", text, re.IGNORECASE):
        return False
    # A wrapper is usually one or two non-comment lines.
    code_lines = [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("//")]
    if len(code_lines) > 2:
        return False
    return True


# ``return`` is deliberately absent: a trailing ``return balance - amount``
# mentions the precondition's identifiers without guarding anything.
_GUARD_STATEMENT_RE = re.compile(
    r"\b(if|elif|assert|raise|match|guard|require|ensure|throw|panic!|except)\b"
)
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CLAUSE_KEYWORDS = {
    "and", "or", "not", "in", "is", "forall", "exists", "implies",
    "true", "false", "True", "False", "None", "Some", "Ok", "Err",
}
_TRIVIAL_REQUIRES = {"", "true", "True", "1"}


def _requires_conditions(requires: str) -> list[str]:
    """Split a requires clause into top-level conjuncts."""
    normalized = requires.replace("&&", " and ")
    parts = re.split(r"\band\b", normalized)
    return [
        part.strip(" ();")
        for part in parts
        if part.strip(" ();") and part.strip() not in _TRIVIAL_REQUIRES
    ]


def _condition_identifiers(condition: str) -> set[str]:
    return {
        token
        for token in _IDENTIFIER_RE.findall(condition)
        if token not in _CLAUSE_KEYWORDS
    }


_C_COMMENT_RE = re.compile(r"/\*[\s\S]*?\*/")
# Masks string-literal contents before comment stripping so `"/api/*"` or
# `"a # b"` is never misread as a comment opener. The inner alternation is
# disjoint (`\\.` vs a non-backslash char) so it cannot backtrack
# exponentially on unterminated literals like `'\\\\\\\\`.
_STRING_LITERAL_RE = re.compile(
    r'''(?P<pre>[A-Za-z]{0,3})(?P<q>["'`])(?P<inner>(?:\\.|[^\\])*?)(?P=q)'''
)
def _skip_literal(s: str, j: int) -> int:
    """Index just past the string literal starting at ``s[j]`` —
    ``'``/``"``/`` ` `` (and triple quotes) with ``\\`` escapes; the
    whole literal, so braces inside it do not affect depth."""
    q = s[j]
    if s[j : j + 3] == q * 3:
        end = s.find(q * 3, j + 3)
        return len(s) if end < 0 else end + 3
    k = j + 1
    while k < len(s):
        if s[k] == "\\":
            k += 2
            continue
        if s[k] == q:
            return k + 1
        k += 1
    return len(s)


def _field_end(s: str, j: int) -> int:
    """Index of the ``}`` closing a replacement field whose depth-1 scan
    starts at ``s[j]``; ``len(s)`` when unbalanced. Quotes are skipped so
    ``f"{a if '}}' else b}"`` does not terminate early."""
    depth = 1
    while j < len(s) and depth:
        if s[j] in "'\"`":
            nxt = _skip_literal(s, j)
            # An unterminated "literal" is e.g. a quote inside a regex —
            # treat it as a plain char instead of losing the field.
            j = nxt if nxt < len(s) else j + 1
            continue
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return len(s)


def _py_interp_exprs(s: str) -> list[str]:
    """Interpolated expressions of a Python f-string body.

    ``{{``/``}}`` are literal-brace escapes outside a replacement field,
    while braces inside one nest normally — ``f"{x:{w}}"`` yields
    ``x:{w}``, ``f"{{name}}"`` yields nothing, ``f"{{{name}}}"`` yields
    ``name``."""
    exprs: list[str] = []
    i, n = 0, len(s)
    while i < n:
        if s[i : i + 2] in ("{{", "}}"):
            i += 2
            continue
        if s[i] == "{":
            j = _field_end(s, i + 1)
            if j < n:
                exprs.append(s[i + 1 : j])
                i = j + 1
                continue
        i += 1
    return exprs


def _ts_interp_exprs(s: str) -> list[str]:
    """``${...}`` expressions of a template literal, braces nesting.
    ``${{ k: v }}`` yields the object literal ``{ k: v }``; a backslash
    escape before ``$`` is literal text, not an interpolation start."""
    exprs: list[str] = []
    i, n = 0, len(s)
    while i + 1 < n:
        if s[i] == "$" and s[i + 1] == "{":
            # `\${` is literal — an odd run of backslashes escapes the `$`.
            run = 0
            while i - run - 1 >= 0 and s[i - run - 1] == "\\":
                run += 1
            if run % 2 == 1:
                i += 1
                continue
            j = _field_end(s, i + 2)
            if j < n:
                exprs.append(s[i + 2 : j])
                i = j + 1
                continue
        i += 1
    return exprs
# Lines that gate execution (as opposed to `raise`/`throw`/`except`, whose
# strings are error messages) keep interpolation expressions visible:
# `if amount > int(f"{limit}")` really does check `limit`.
_CONDITIONAL_LINE_RE = re.compile(
    r"^\s*(?:if|elif|assert|while|match|guard|require|ensure|when)\b"
)
# A ``key:`` inside a TS object literal — a label, not a variable read.
# The lookbehind keeps ternary values (``cond ? allowed : false``) intact:
# a real key only sits right after ``{`` or ``,``.
_TS_BRACED_GROUP_RE = re.compile(r"\{[^{}]*\}")
_TS_OBJECT_KEY_RE = re.compile(r"(?<=[{,])\s*[A-Za-z_]\w*\s*:")


def _literal_close(s: str, start: int, q: str, is_f: bool) -> int:
    """Index just past the closing quote of a literal whose inner text
    starts at ``s[start]``; ``-1`` when unterminated. For f-strings and
    template literals the close only counts at replacement-field depth 0,
    and literals nested inside a field (or a stray ``'`` in a regex) are
    skipped."""
    k, field_depth, ts = start, 0, q == "`"
    n = len(s)
    while k < n:
        c = s[k]
        if c == "\\":
            k += 2
            continue
        if is_f or ts:
            if ts and s[k : k + 2] == "${":
                field_depth += 1
                k += 2
                continue
            if is_f and c == "{":
                if s[k : k + 2] == "{{":
                    k += 2
                    continue
                field_depth += 1
                k += 1
                continue
            if c == "}" and field_depth > 0:
                field_depth -= 1
                k += 1
                continue
            if field_depth > 0 and c in "'\"`":
                nxt = _skip_literal(s, k)
                k = nxt if nxt < n else k + 1
                continue
        if c == q and field_depth == 0:
            return k + 1
        k += 1
    return -1


def _line_comment_seen(out: list[str]) -> bool:
    """Whether the already-masked text contains a `//` comment opener —
    one outside a `/* */` block comment and not preceded by `:` (URL
    scheme) or `\\` (regex escape). Scanned left to right so a `/*`
    after `//` never counts as a block opener either."""
    text = "".join(out)
    i, n = 0, len(text)
    while i < n - 1:
        pair = text[i : i + 2]
        if pair == "//":
            if i == 0 or text[i - 1] not in ":\\":
                return True
            i += 1
            continue
        if pair == "/*":
            end = text.find("*/", i + 2)
            if end < 0:
                return False  # the rest is inside a block comment
            i = end + 2
            continue
        i += 1
    return False


def _strip_ts_comments(line: str) -> tuple[str, bool]:
    """Strip `//` and `/* */` comments from a string-masked line in one
    left-to-right pass; whichever opener comes first wins, so `/*`
    inside a `//` comment and `//` inside a block comment are ignored.
    Returns the stripped line and whether it ends inside a block
    comment."""
    out: list[str] = []
    i, n = 0, len(line)
    while i < n - 1:
        pair = line[i : i + 2]
        if pair == "//":
            break
        if pair == "/*":
            end = line.find("*/", i + 2)
            if end < 0:
                return "".join(out), True
            # A space keeps the comment from joining two tokens.
            out.append(" ")
            i = end + 2
            continue
        out.append(line[i])
        i += 1
    else:
        # The loop only ends early via `break`; the trailing char pair is
        # still unexamined when n - i <= 1.
        out.append(line[i:])
    return "".join(out), False


def _mask_line_strings(
    line: str, keep_interp: bool
) -> tuple[str, tuple[str, bool, str] | None]:
    """Mask every string literal in ``line`` to empty quotes.

    Returns the masked text plus ``(quote, is_f, inner_tail)`` when a
    multiline literal (template or triple-quoted) ran unterminated to
    the end of the line — the caller resumes the close-scan on the next
    line and evaluates the accumulated inner text. Unlike a regex
    approach, the literal's own quote inside ``{...}`` fields (PEP 701)
    does not end it early."""
    out: list[str] = []
    i, n = 0, len(line)
    open_lit: tuple[str, bool, str] | None = None
    while i < n:
        if line[i] not in "'\"`":
            out.append(line[i])
            i += 1
            continue
        # A quote's prefix letters (r/b/f/u) are part of the literal —
        # drop them so `r"x"` does not leave `r` as an identifier.
        p = i
        while p > 0 and line[p - 1] in "rbufRBUF":
            p -= 1
        del out[len(out) - (i - p) :]
        prefix = line[p:i].lower()
        q = line[i]
        if q == "`" and _line_comment_seen(out):
            # `//` already appeared on this line outside a string — the
            # backtick is comment text, not a template start.
            out.append(q)
            i += 1
            continue
        # A ' or " immediately after an identifier char is an apostrophe
        # inside text (``don't``, ``it's fine \``), never a literal
        # start — even with a trailing backslash that would otherwise
        # open a line continuation. A backtick after an identifier is a
        # TS tagged template, which still is a literal.
        if q != "`" and p > 0 and (line[p - 1].isalnum() or line[p - 1] == "_"):
            out.append(q)
            i += 1
            continue
        is_f = "f" in prefix and q != "`"
        if line[i : i + 3] == q * 3:
            end = line.find(q * 3, i + 3)
            inner = line[i + 3 : n if end < 0 else end]
            i = n if end < 0 else end + 3
            if end < 0:
                # Kept expressions wait for the closing line — the caller
                # evaluates the whole multi-line inner at once.
                out.append(q * 6)
                open_lit = (q * 3, is_f, inner)
            else:
                out.append(q * 6 + _kept_exprs(inner, q, is_f, keep_interp))
            continue
        end = _literal_close(line, i + 1, q, is_f)
        if end < 0 and (q == "`" or line[i + 1 :].rstrip().endswith("\\")):
            # A template literal can span lines, and a ' or " literal may
            # continue onto the next line via a trailing backslash — the
            # continuation state keeps the inner text for the caller.
            inner = line[i + 1 :]
            i = n
            out.append(q * 2)
            open_lit = (q, is_f, inner)
        elif end < 0:
            # An unterminated ' or " is no literal — single-line quotes
            # cannot span lines, so this is an apostrophe inside a
            # comment or other text ("Don't", "can't"). Keep it as text.
            out.append(line[i:])
            i = n
        else:
            inner = line[i + 1 : end - 1]
            i = end
            out.append(q * 2 + _kept_exprs(inner, q, is_f, keep_interp))
    return "".join(out), open_lit


def _kept_exprs(inner: str, quote: str, is_f: bool, keep_interp: bool) -> str:
    """Kept interpolation expressions for one literal, or ``""``."""
    if not keep_interp:
        return ""
    if quote == "`":
        found = _ts_interp_exprs(inner)
    elif is_f:
        found = _py_interp_exprs(inner)
    else:
        found = []
    kept: list[str] = []
    for expr in found:
        # Nested literals inside the expression (``f"{d['balance']}"``)
        # hold literal text, not references — mask them out too.
        expr = _STRING_LITERAL_RE.sub(_mask_string_literal, expr)
        if quote == "`":
            # A nested template literal inside the expression
            # (``${`if cond`}``) holds text, not code — mask it whole so
            # its contents are not read as guards or variable reads.
            expr = _TS_NESTED_TEMPLATE_RE.sub("``", expr)
            # Comments inside the interpolation (``${/* c */ x}``,
            # ``${x // c}``) hold names that are not reads. Regexes are
            # masked before ``//`` stripping: a pattern ending in
            # ``\//`` (``/a\/\//``) must not lose its closing slash.
            expr = _TS_BLOCK_COMMENT_RE.sub(" ", expr)
            expr = _mask_ts_regexes(_strip_ts_object_keys(expr))
            expr = _TS_LINE_COMMENT_RE.sub(" ", expr)
        else:
            expr = _strip_format_spec(expr)
        # Blank comment-, comma- and depth-significant characters
        # (``#``, ``/``, ``,``, brackets) so the comment stripping,
        # assert-message splitting and logical-line joining after
        # masking are not affected by the expression's syntax.
        expr = re.sub(r"[#/,()\[\]{}]", " ", expr)
        if expr.strip():
            kept.append(expr)
    return " " + " ".join(kept) if kept else ""


def _mask_string_literal(match: re.Match[str]) -> str:
    """Replace a literal with empty quotes.

    Interpolation expressions (``f"{x}"``, ``${x}``) are dropped: on a
    non-conditional line they most often sit inside an error *message*
    such as ``raise ValueError(f"balance {balance} < amount {amount}")``
    and would let a guard pass on identifiers it never checks."""
    return match.group("q") * 2


_TS_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_TS_LINE_COMMENT_RE = re.compile(r"//[^\n]*")
_TS_NESTED_TEMPLATE_RE = re.compile(r"`(?:\\.|[^`\\])*`")
_TS_REGEX_START_CHARS = "(,=:!?&|[{~^+*%-<>;"


def _postfix_incdec_before(expr: str, i: int) -> bool:
    """Whether ``expr[i]`` sits right after a postfix ``++``/``--`` —
    the two operator chars are adjacent and follow an operand (spaces
    allowed between operand and operator, and between operator and the
    ``/``), unlike spaced binary+unary ``a + +``."""
    k = i - 1
    while k >= 0 and expr[k].isspace():
        k -= 1
    if k < 2 or expr[k] not in "+-" or expr[k - 1] != expr[k]:
        return False
    k -= 2
    while k >= 0 and expr[k].isspace():
        k -= 1
    return k >= 0 and (expr[k].isalnum() or expr[k] in "_)]}")


def _mask_ts_regexes(expr: str) -> str:
    """Blank ``/.../`` regex-literal contents so pattern text
    (``/balance|amount/``) is not read as variable references. A ``/``
    opens a regex only after an operator-ish char — ``a / b`` division
    is left alone, and so is division after a postfix ``++``/``--``
    (``counter++ / amount``)."""
    out: list[str] = []
    prev = ""  # last non-space char seen
    i, n = 0, len(expr)
    while i < n:
        c = expr[i]
        if c == "/" and expr[i : i + 2] == "//":
            # A line comment, never a regex — the // stripping pass
            # after this removes its body.
            out.append(c)
            prev = c
            i += 1
            continue
        if c == "/" and (
            not prev
            or (prev in _TS_REGEX_START_CHARS and not _postfix_incdec_before(expr, i))
        ):
            j = i + 1
            in_class = False
            while j < n:
                if expr[j] == "\\":
                    j += 2
                    continue
                if expr[j] == "[":
                    in_class = True
                elif expr[j] == "]":
                    in_class = False
                elif expr[j] == "/" and not in_class:
                    break
                j += 1
            if j < n:
                # Spaces (not ``//``): the masked regex must not look
                # like a comment to the ``//`` stripping pass later.
                out.append(" " * (j + 1 - i))
                prev = "/"
                i = j + 1
                continue
        out.append(c)
        if not c.isspace():
            prev = c
        i += 1
    return "".join(out)


def _strip_ts_object_keys(expr: str) -> str:
    """Object-literal keys are labels, not reads — ``${{balance: 1}}``
    mentions ``balance`` without reading it. Strip ``key:`` inside each
    braced group (repeated for nesting), after dropping ``/* */``
    comments (replaced by a space so tokens stay separated) that could
    sit between the ``{`` and the key."""
    prev = None
    while prev != expr:
        prev = expr
        expr = _TS_BRACED_GROUP_RE.sub(
            lambda m: _TS_OBJECT_KEY_RE.sub(
                ":", _TS_BLOCK_COMMENT_RE.sub(" ", m.group(0))
            ),
            expr,
        )
    return expr


def _strip_format_spec(expr: str) -> str:
    """Drop an f-string format specifier — the ``:...`` suffix — so its
    characters (``{y:#x}``'s ``x``) are not counted as variable references.
    Colons inside brackets/braces (slices, dicts) stay.``!r``-style
    conversions end the value but a ``:`` spec may still follow
    (``f"{v!r:{w}}"`` reads ``w``), so the scan keeps going after ``!``.
    A dynamic spec still *reads* variables (``f"{x:{width}}"`` reads
    ``width``), so interpolations nested in the spec are kept — each
    stripped of its own spec recursively (``{width:d}`` yields ``width``)."""
    cut = None
    depth = 0
    for i, ch in enumerate(expr):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == ":" and depth == 0:
            head = expr[: cut if cut is not None else i]
            inner = " ".join(
                _strip_format_spec(e) for e in _py_interp_exprs(expr[i + 1 :])
            )
            return head + (" " + inner if inner.strip() else "")
        elif (
            ch == "!"
            and depth == 0
            and cut is None
            and i + 1 < len(expr)
            and expr[i + 1] in "rsa"
        ):
            cut = i
    return expr[:cut] if cut is not None else expr


def _drop_assert_message(line: str) -> str:
    """Cut an ``assert`` line at the first top-level ``,``.

    The part after the comma is the failure *message*, not the condition:
    ``assert amount > 0, f"{balance} too low"`` only checks ``amount``.
    Runs on the string-masked line, so commas inside literals are gone and
    commas inside kept interpolation expressions sit at brace depth > 0.
    """
    if not re.match(r"^\s*assert\b", line):
        return line
    depth = 0
    for i, ch in enumerate(line):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            return line[:i]
    return line


def _guard_source_lines(body: str, language: str = "") -> list[str]:
    """Return logical body lines with comments and docstrings stripped.

    Lines inside an unclosed parenthesis are joined so a guard written across
    several lines (``if (\n    amount > balance\n):``) is still seen as one
    candidate.
    """
    lang = _canonical_language(language) or language.lower()
    cleaned: list[str] = []
    in_docstring: str | None = None
    in_block_comment = False
    cont_literal: tuple[str, bool, bool, list[str]] | None = None
    for raw in body.splitlines():
        line = raw
        if cont_literal is not None:
            # A multiline literal (template or triple-quoted) is still
            # open — accumulate its inner text, then emit the kept
            # interpolation expressions on the closing line. Comparisons
            # inside ``${...}`` on continuation lines are real code.
            cq, cisf, ckeep, cbuf = cont_literal
            if len(cq) == 1:
                end = _literal_close(line, 0, cq, cisf or cq == "`")
                if end < 0:
                    cbuf.append(line)
                    continue
                cbuf.append(line[: end - 1])
                line = line[end:]
            else:
                end = line.find(cq)
                if end < 0:
                    cbuf.append(line)
                    continue
                cbuf.append(line[:end])
                line = line[end + len(cq) :]
            kept = _kept_exprs("\n".join(cbuf), cq[0], cisf, ckeep)
            line = cq[0] * 2 + kept + line
            cont_literal = None
        if in_block_comment:
            if "*/" in line:
                line = line.split("*/", 1)[1]
                in_block_comment = False
            else:
                continue
        if in_docstring is not None:
            if in_docstring in line:
                line = line.split(in_docstring, 1)[1]
                in_docstring = None
            else:
                continue
        if lang == "python":
            for quote in ('"""', "'''"):
                if quote in line:
                    head, _, tail = line.partition(quote)
                    if quote in tail:
                        line = head + tail.split(quote, 1)[1]
                    else:
                        line = head
                        in_docstring = quote
                    break
        # Mask string-literal contents so a `#`, `//` or `/*` inside a
        # string ("/api/*", "a # b") is never read as a comment opener.
        keep_interp = _CONDITIONAL_LINE_RE.match(line) is not None
        line, open_lit = _mask_line_strings(line, keep_interp)
        if open_lit is not None:
            cq, cisf, cinner = open_lit
            cont_literal = (cq, cisf, keep_interp, [cinner])
        if lang != "python":
            # One pass for both comment kinds: `//` inside `/* */` and
            # `/*` inside `//` are comment text, not openers. `//` is a
            # comment in C-family languages but Python's floor division,
            # so this is skipped for Python bodies.
            line, in_block_comment = _strip_ts_comments(line)
        line = line.split("#", 1)[0]
        if line.strip():
            cleaned.append(line)
    logical: list[str] = []
    depth = 0
    for line in cleaned:
        if logical and depth > 0:
            logical[-1] += " " + line.strip()
        else:
            logical.append(line)
        # Only parens/brackets continue a logical line in brace languages —
        # a `{` opens a block there, and joining `if cond {` with the next
        # line would merge the condition with the block's body. Python has
        # no block braces: `{` is always a dict/set literal, so a multi-line
        # set in `if value not in {\n  a,\n  b\n}:` still joins.
        openers = "([{" if lang == "python" else "(["
        closers = ")]}" if lang == "python" else ")]"
        depth += sum(line.count(c) for c in openers)
        depth -= sum(line.count(c) for c in closers)
    # Drop assert failure messages on the *joined* logical line — doing it
    # per physical line would orphan the continuation of a multi-line
    # assert whose opening `(` sat after the comma.
    return [_drop_assert_message(line) for line in logical]


_FORWARD_RETURN_RE = re.compile(
    r"\breturn\s+[A-Za-z_][\w.]*\s*\((?P<args>[^()]*)\)"
)
# An argument is a plain identifier (``balance``, ``s.balance``). Python
# also has keyword-argument forwards (``balance=balance``); in C-family
# languages ``a = b`` inside a call is an assignment, not a kwarg, so it
# is only accepted when the language is Python.
_FORWARD_ARG_RE = re.compile(r"^[A-Za-z_][\w.]*$")
_FORWARD_KWARG_RE = re.compile(r"^[A-Za-z_][\w.]*\s*=\s*[A-Za-z_][\w.]*$")
_CALL_SITE_RE = re.compile(r"(?P<callee>[A-Za-z_][\w.]*)\s*\(")
_VALIDATION_TOKENS = (
    "check", "valid", "ensure", "verify", "require", "guard",
    "assert", "reject", "enforce", "insufficient", "forbid",
)


def _is_validation_call(callee: str) -> bool:
    lowered = callee.lower()
    return any(token in lowered for token in _VALIDATION_TOKENS)


def _is_pure_call_forward(lines: list[str], language: str = "") -> bool:
    """True when the body is only ``return callee(ident, ident, ...)``.

    A forward that passes raw identifiers may delegate the check to the
    callee; ``return round(balance - amount, 2)`` computes instead and does
    not get the exemption. Python keyword arguments (``x=x``) count as
    forwards; in C-family languages the same text is an assignment and
    must not exempt the body.
    """
    lang = _canonical_language(language) or language.lower()
    text = " ".join(lines)
    match = _FORWARD_RETURN_RE.search(text)
    if not match:
        return False
    args = [a.strip() for a in match.group("args").split(",") if a.strip()]
    return bool(args) and all(
        _FORWARD_ARG_RE.match(a)
        or (lang == "python" and _FORWARD_KWARG_RE.match(a))
        for a in args
    )


_NESTED_DEF_RE = re.compile(r"(?:async\s+)?(?:def|class)\s+([A-Za-z_]\w*)")


def _include_called_nested_guards(
    lines: list[str],
) -> tuple[list[str], list[str]]:
    """Keep a nested ``def``/``class`` block's guard lines only when the
    enclosing body actually calls it.

    A nested helper that is never called cannot enforce anything, so its
    ``if``/``raise`` lines must not count as the outer function's
    enforcement; a called helper's lines do count.

    Returns ``(outer, merged)``: ``outer`` is the enclosing body's own
    lines, ``merged`` adds the called nested blocks' lines. Callers that
    judge the outer function itself (e.g. the pure call-forward check)
    must use ``outer``; enforcement scanning uses ``merged``.
    """
    main: list[str] = []
    nested: dict[str, list[str]] = {}
    current: str | None = None
    nested_indent = -1
    for line in lines:
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        match = _NESTED_DEF_RE.match(stripped)
        if match:
            current = match.group(1)
            nested_indent = indent
            nested.setdefault(current, [])
            # A one-line nested def (``def check(): assert x``) carries its
            # guard on the def line itself — keep the body after the
            # signature's closing ``):``, or after the return annotation's
            # ``-> T:`` (a bare last-``:`` split would clip a body holding
            # a dict or slice).
            _, _, tail = stripped.partition("):")
            if not tail.strip():
                ret = re.search(r"->[^:]*:", stripped)
                tail = stripped[ret.end():] if ret else ""
                if not tail.strip():
                    _, _, tail = stripped.rpartition(":")
            if tail.strip():
                nested[current].append(tail)
            continue
        if current is not None and indent > nested_indent:
            nested[current].append(line)
            continue
        current = None
        main.append(line)
    out = list(main)
    # Re-add a nested block's lines when the body calls it — directly from
    # the outer level or transitively through another included helper.
    # A dotted call (``self.check()``, ``obj.check()``) is a method, not the
    # local function, so it must not pull the nested block in.
    pending = dict(nested)
    while pending:
        progressed = False
        for name, nested_lines in list(pending.items()):
            call_re = rf"(?<![\w.]){re.escape(name)}\s*\("
            if any(re.search(call_re, line) for line in out):
                out.extend(nested_lines)
                del pending[name]
                progressed = True
        if not progressed:
            break
    # The forward-check exemption applies to the audited function's own
    # lines only — a nested helper's ``return f(...)`` must not make the
    # outer body look like a pure call-forward.
    return main, out


def _has_unenforced_precondition(requires: str, body: str, language: str = "") -> bool:
    """True when a spec precondition names identifiers no guard covers.

    The audit's extracted ``requires`` should mirror defensive checks present
    in the source. When the spec assumes a condition (``amount <= balance``)
    that no ``if``/``assert``/``raise``/``throw``/``guard``
    statement in the body mentions together, the precondition was conjured —
    it is assumed, not enforced — so verification is vacuous on that clause.
    """
    if not requires or requires.strip() in _TRIVIAL_REQUIRES:
        return False
    lines = _guard_source_lines(body, language)
    lang = _canonical_language(language) or language.lower()
    outer_lines = lines
    if lang == "python":
        outer_lines, lines = _include_called_nested_guards(lines)
    if _is_pure_call_forward(outer_lines, language):
        return False
    # Guard statements (if/assert/raise/throw/...) plus validation-named call
    # sites that may delegate the check (``self._ensure_balance(amount)``).
    # Calls like ``print(balance, amount)`` touch the identifiers without
    # enforcing anything, so only validation-flavoured callee names count.
    enforcement_lines = [
        line
        for line in lines
        if _GUARD_STATEMENT_RE.search(line)
        or (
            not line.lstrip().startswith("return")
            and any(
                _is_validation_call(m.group("callee"))
                for m in _CALL_SITE_RE.finditer(line)
            )
        )
    ]
    for condition in _requires_conditions(requires):
        identifiers = _condition_identifiers(condition)
        if not identifiers:
            continue
        if not any(
            identifiers <= set(_IDENTIFIER_RE.findall(line))
            for line in enforcement_lines
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CrossValidationReport:
    """Result of cross-validating a spec against its implementation."""

    spec_stronger_than_impl: list[str] = field(default_factory=list)
    impl_stronger_than_spec: list[str] = field(default_factory=list)
    uncovered_atoms: list[str] = field(default_factory=list)
    drift_detected: bool = False
    coverage_ratio: float = 0.0
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def is_consistent(self) -> bool:
        return (
            not self.spec_stronger_than_impl
            and not self.impl_stronger_than_spec
            and not self.uncovered_atoms
            and not self.drift_detected
        )


@dataclass
class DriftReport:
    """Report of spec drift between two proof certificates."""

    changed_atoms: list[str] = field(default_factory=list)
    new_atoms: list[str] = field(default_factory=list)
    removed_atoms: list[str] = field(default_factory=list)
    drift_detected: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# CrossValidator
# ---------------------------------------------------------------------------


class CrossValidator:
    """Cross-validate Mumei specs against implementation code."""

    def validate_spec_vs_impl(
        self,
        spec_path: str,
        impl_path: str,
        language: str,
    ) -> CrossValidationReport:
        """Compare spec atoms with implementation functions.

        Detects:
        - spec_stronger_than_impl: spec atoms with contracts that reference
          constraints not reflected in the implementation structure.
        - impl_stronger_than_spec: implementation functions with complex
          validation logic not captured in any spec atom.
        - uncovered_atoms: spec atoms with no corresponding implementation
          function.

        Args:
            spec_path: Path to .mm specification file.
            impl_path: Path to implementation source file.
            language: Language of the implementation (python/rust/typescript/go/solidity).

        Returns:
            CrossValidationReport with semantic gap analysis.
        """
        report = CrossValidationReport()

        # Read files
        try:
            spec_source = Path(spec_path).read_text(encoding="utf-8")
        except OSError as exc:
            report.details.append(f"Failed to read spec: {exc}")
            return report

        try:
            impl_source = Path(impl_path).read_text(encoding="utf-8")
        except OSError as exc:
            report.details.append(f"Failed to read implementation: {exc}")
            return report

        # Extract atoms and functions
        spec_atoms = _extract_spec_atoms(spec_source)
        impl_functions = _extract_functions(impl_source, language)

        if not spec_atoms:
            report.details.append("No spec atoms found in spec file.")
            return report

        # Coverage analysis (normalization-tolerant: snake_case / camelCase /
        # leading-underscore differences between the two extractors must not
        # register as false "no matching implementation" gaps).
        spec_by_canon: dict[str, str] = {}
        for atom in spec_atoms:
            spec_by_canon.setdefault(_canonical_symbol(atom["name"]), atom["name"])
        impl_by_canon = {_canonical_symbol(func): func for func in impl_functions}

        report.uncovered_atoms = sorted(
            original
            for canon, original in spec_by_canon.items()
            if canon not in impl_by_canon
        )

        covered = set(spec_by_canon) & set(impl_by_canon)
        report.coverage_ratio = len(covered) / len(spec_by_canon) if spec_by_canon else 0.0

        # Semantic gap detection: spec stronger than impl
        # If the spec has complex requires/ensures but the implementation
        # function is trivial (heuristic: short or no validation code)
        for atom in spec_atoms:
            impl_name = impl_by_canon.get(_canonical_symbol(atom["name"]))
            if impl_name is None:
                continue
            has_complex_contract = bool(atom["requires"]) and len(atom["requires"]) > 20
            has_nontrivial_requires = bool(atom["requires"]) and atom["requires"].strip() not in _TRIVIAL_REQUIRES
            if has_complex_contract or has_nontrivial_requires:
                body = _extract_function_body(impl_source, language, impl_name)
                if body and _has_unenforced_precondition(atom["requires"], body, language):
                    report.spec_stronger_than_impl.append(atom["name"])
                    # The requires literal itself is not echoed: spec text may
                    # contain sensitive values and diagnostics are forwarded to
                    # MCP clients.
                    report.details.append(
                        f"spec precondition assumed, not enforced, by `{impl_name}`"
                    )
                    continue
                if body and has_complex_contract and len(body.strip()) < len(atom["requires"]):
                    if _is_short_native_or_wrapper_body(body):
                        continue
                    report.spec_stronger_than_impl.append(atom["name"])

        # Semantic gap detection: impl stronger than spec
        # Functions with complex validation that have no spec or trivial spec
        for func_name in impl_functions:
            matching_atom = next(
                (a for a in spec_atoms if _canonical_symbol(a["name"]) == _canonical_symbol(func_name)),
                None,
            )
            if matching_atom is None:
                continue
            if not matching_atom["requires"] and not matching_atom["ensures"]:
                # Impl exists but spec is trivial
                report.impl_stronger_than_spec.append(func_name)

        return report

    def detect_spec_drift(
        self,
        old_cert: dict[str, Any],
        new_cert: dict[str, Any],
    ) -> DriftReport:
        """Detect spec drift by comparing proof certificate content hashes.

        Compares the ``content_hash`` fields of atoms in old and new
        certificates to determine which atoms have been added, removed, or
        modified.

        Args:
            old_cert: Previous proof certificate (parsed JSON).
            new_cert: Current proof certificate (parsed JSON).

        Returns:
            DriftReport with changed/new/removed atoms.
        """
        old_atoms = {
            a["name"]: a.get("content_hash", "")
            for a in old_cert.get("atoms", [])
        }
        new_atoms = {
            a["name"]: a.get("content_hash", "")
            for a in new_cert.get("atoms", [])
        }

        old_names = set(old_atoms.keys())
        new_names = set(new_atoms.keys())

        changed = sorted(
            name
            for name in old_names & new_names
            if old_atoms[name] != new_atoms[name]
        )
        new = sorted(new_names - old_names)
        removed = sorted(old_names - new_names)

        return DriftReport(
            changed_atoms=changed,
            new_atoms=new,
            removed_atoms=removed,
            drift_detected=bool(changed or new or removed),
        )

    def check_impl_coverage(
        self,
        spec_atoms: list[str],
        impl_functions: list[str],
    ) -> dict[str, Any]:
        """Compute coverage ratio of spec atoms against implementation functions.

        Args:
            spec_atoms: List of spec atom names.
            impl_functions: List of implementation function names.

        Returns:
            Dict with ``covered``, ``uncovered``, ``extra``, and ``ratio``.
        """
        spec_by_canon: dict[str, str] = {}
        for name in spec_atoms:
            spec_by_canon.setdefault(_canonical_symbol(name), name)
        impl_by_canon: dict[str, str] = {}
        for name in impl_functions:
            impl_by_canon.setdefault(_canonical_symbol(name), name)

        covered_canon = set(spec_by_canon) & set(impl_by_canon)
        covered = sorted(spec_by_canon[c] for c in covered_canon)
        uncovered = sorted(
            original for canon, original in spec_by_canon.items() if canon not in impl_by_canon
        )
        extra = sorted(
            original for canon, original in impl_by_canon.items() if canon not in spec_by_canon
        )
        ratio = len(covered_canon) / len(spec_by_canon) if spec_by_canon else 0.0

        return {
            "covered": covered,
            "uncovered": uncovered,
            "extra_in_impl": extra,
            "ratio": ratio,
        }
