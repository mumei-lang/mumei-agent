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


def _guard_source_lines(body: str, language: str = "") -> list[str]:
    """Return logical body lines with comments and docstrings stripped.

    Lines inside an unclosed parenthesis are joined so a guard written across
    several lines (``if (\n    amount > balance\n):``) is still seen as one
    candidate.
    """
    lang = language.lower()
    cleaned: list[str] = []
    in_docstring: str | None = None
    in_block_comment = False
    for raw in body.splitlines():
        line = raw
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
        if lang != "python":
            while "/*" in line:
                head, _, tail = line.partition("/*")
                if "*/" in tail:
                    line = head + tail.split("*/", 1)[1]
                else:
                    line = head
                    in_block_comment = True
                    break
            line = _C_COMMENT_RE.sub(" ", line)
        line = line.split("#", 1)[0]
        if lang != "python":
            # `//` is a comment in C-family languages but the floor-division
            # operator in Python — only strip it for non-Python bodies.
            line = line.split("//", 1)[0]
        if line.strip():
            cleaned.append(line)
    logical: list[str] = []
    depth = 0
    for line in cleaned:
        if logical and depth > 0:
            logical[-1] += " " + line.strip()
        else:
            logical.append(line)
        depth += line.count("(") + line.count("[") + line.count("{")
        depth -= line.count(")") + line.count("]") + line.count("}")
    return logical


_FORWARD_RETURN_RE = re.compile(
    r"\breturn\s+[A-Za-z_][\w.]*\s*\((?P<args>[^()]*)\)"
)
_FORWARD_ARG_RE = re.compile(r"^[A-Za-z_][\w.]*$")
_CALL_SITE_RE = re.compile(r"(?P<callee>[A-Za-z_][\w.]*)\s*\(")
_VALIDATION_TOKENS = (
    "check", "valid", "ensure", "verify", "require", "guard",
    "assert", "reject", "enforce", "insufficient", "forbid",
)


def _is_validation_call(callee: str) -> bool:
    lowered = callee.lower()
    return any(token in lowered for token in _VALIDATION_TOKENS)


def _is_pure_call_forward(lines: list[str]) -> bool:
    """True when the body is only ``return callee(ident, ident, ...)``.

    A forward that passes raw identifiers may delegate the check to the
    callee; ``return round(balance - amount, 2)`` computes instead and does
    not get the exemption.
    """
    text = " ".join(lines)
    match = _FORWARD_RETURN_RE.search(text)
    if not match:
        return False
    args = [a.strip() for a in match.group("args").split(",") if a.strip()]
    return bool(args) and all(_FORWARD_ARG_RE.match(a) for a in args)


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
    if _is_pure_call_forward(lines):
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
