"""Foreign-code contract inference helpers for foreign code strategy."""
from __future__ import annotations

import ast
from datetime import datetime, timezone
from fractions import Fraction
from dataclasses import dataclass, field
import hashlib
import json
import re
from pathlib import Path
from typing import Iterable

import z3

from agent import semantic_safety, tree_sitter_extract
from agent.cross_validation_foreign import (
    SOLIDITY_UINT256_MAX,
    _addition_pairs_regex,
    _dedupe_strings,
    _extract_return_expression,
    _go_function_declarations,
    _go_nillable_param_names,
    _go_type_is_nillable,
    _go_param_types,
    _is_go_test_name,
    _local_variable_names,
    _mask_nested_function_literals,
    _split_params,
    _strip_go_rust_literals_and_comments,
)

_SOLIDITY_FUNCTION_PATTERN = re.compile(
    r"function\s+(?P<name>[A-Za-z_$][\w$]*)\s*"
    r"\((?P<params>[^)]*)\)"
    r"(?P<attrs>[^{;]*?)\{",
    re.DOTALL,
)
_SOLIDITY_EXTERNAL_CALL_PATTERNS = (
    re.compile(r"\.call\s*\{[^}]*value\s*:", re.DOTALL),
    re.compile(r"\.call\s*\(", re.DOTALL),
    re.compile(r"\.transfer\s*\(", re.DOTALL),
    re.compile(r"\.send\s*\(", re.DOTALL),
)
_SOLIDITY_STORAGE_WRITE_PATTERN = re.compile(
    r"(?:^|;|\{)\s*(?P<lhs>[A-Za-z_][\w$]*(?:\[[^\]]+\]|\.[A-Za-z_][\w$]*)*)\s*"
    r"(?P<op>(?<![=!<>])=(?![=])|\+=|-=|\*=)",
    re.DOTALL | re.MULTILINE,
)
_SOLIDITY_LOCAL_DECLARATION_PATTERN = re.compile(
    r"^(?:"
    r"uint(?:8|16|32|64|128|256)?|"
    r"int(?:8|16|32|64|128|256)?|"
    r"bool|"
    r"address(?:\s+payable)?|"
    r"bytes(?:\d+)?|"
    r"string|"
    r"mapping\b|"
    r"[A-Z][\w$]*\s+(?:memory|storage|calldata)\b"
    r")",
    re.DOTALL,
)
_SOLIDITY_ACCESS_MODIFIER_PATTERN = re.compile(r"\bonly[A-Z]\w*|\bauth\b")
_SOLIDITY_ACCESS_GUARD_PATTERNS = (
    re.compile(r"require\s*\(\s*msg\.sender\s*=="),
    re.compile(r"require\s*\(\s*(?:_?owner|owner\(\))"),
    re.compile(r"hasRole\s*\("),
    re.compile(r"_checkOwner\s*\("),
    re.compile(r"_checkRole\s*\("),
    re.compile(
        r"if\s*\(\s*(?:msg\.sender\s*[!=]=\s*(?:_?owner|owner\(\))|"
        r"(?:_?owner|owner\(\))\s*[!=]=\s*msg\.sender)[^)]*\)\s*revert\b",
        re.DOTALL,
    ),
    re.compile(
        r"if\s*\(\s*(?:msg\.sender\s*[!=]=\s*(?:_?owner|owner\(\))|"
        r"(?:_?owner|owner\(\))\s*[!=]=\s*msg\.sender)[^)]*\)\s*\{[^}]*\brevert\b",
        re.DOTALL,
    ),
)
_SOLIDITY_REENTRANCY_GUARD_MODIFIER_PATTERN = re.compile(
    r"\b(?:nonReentrant|noReentrancy|nonreentrant)\b",
    re.IGNORECASE,
)
_SOLIDITY_MANUAL_LOCK_REQUIRE_PATTERNS = (
    re.compile(r"require\s*\(\s*!\s*(?P<var>[A-Za-z_$][\w$]*)\b"),
    re.compile(r"require\s*\(\s*(?P<var>[A-Za-z_$][\w$]*)\s*==\s*false\b", re.IGNORECASE),
)
_SOLIDITY_OP_TRACE_PATTERN = re.compile(
    r"(?P<externalCall>\.call\s*\{[^}]*value\s*:\s*[^}]*\}|\.[cC]all\s*\(|\.transfer\s*\(|\.send\s*\()"
    r"|(?P<stateWrite>(?:^|;|\{)\s*(?P<lhs>[A-Za-z_][\w$]*(?:\[[^\]]+\]|\.[A-Za-z_][\w$]*)*)\s*"
    r"(?P<op>(?<![=!<>])=(?![=])|\+=|-=|\*=))",
    re.DOTALL | re.MULTILINE,
)
_SOLIDITY_GUARD_UNLOCKED = z3.IntVal(0)
_SOLIDITY_GUARD_LOCKED = z3.IntVal(1)

@dataclass(frozen=True)
class ForeignCodeSpec:
    """Function-level contract inferred from foreign source code."""

    function_name: str
    params: dict[str, str]
    return_type: str
    preconditions: list[str] = field(default_factory=list)
    postconditions: list[str] = field(default_factory=list)
    source_line: int = 0

@dataclass(frozen=True)
class ForeignSafetyIssue:
    function_name: str
    message: str
    required_contracts: tuple[str, ...] = ()
    counterexample: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class _SolidityOpTraceItem:
    kind: str
    offset: int
    snippet: str

_MUMEI_CONTRACT_BUILTINS = frozenset(
    {
        "len",
        "forall",
        "exists",
        "old",
        "abs",
        "min",
        "max",
        "sum",
        "implies",
        "result",
        "int",
        "bool",
    }
)
_CALL_CALLEE_RE = re.compile(r"\b(?P<callee>[A-Za-z_]\w*)\s*\(")


def _clause_references_undeclared_helper(clause: str, declared: set[str]) -> bool:
    """True when ``clause`` calls a helper atom that the skeleton doesn't declare.

    A generated ``ensures`` such as ``result == Hex2Bytes(s)`` can never verify
    in a single-atom skeleton because ``Hex2Bytes`` is undefined there. Such
    clauses are dropped rather than emitted (#283).
    """
    for match in _CALL_CALLEE_RE.finditer(clause):
        callee = match.group("callee")
        if callee in _MUMEI_CONTRACT_BUILTINS or callee in declared:
            continue
        return True
    return False


def to_mumei_atom(spec: ForeignCodeSpec) -> str:
    """Convert a foreign-code contract into Mumei atom syntax."""
    params = ", ".join(
        f"{_safe_identifier(name)}: {_mumei_type(type_name)}"
        for name, type_name in spec.params.items()
    )
    return_type = _mumei_type(spec.return_type)
    if return_type in ("i64", "u64") and any(
        re.search(r'result\s*==\s*"[^"]*"', clause) for clause in spec.postconditions
    ):
        # Named string types (e.g. backendplugin.Target) return string literals.
        return_type = "string"
    requires = _join_contracts(spec.preconditions)
    declared = {
        _safe_identifier(spec.function_name),
        *(_safe_identifier(name) for name in spec.params),
    }
    safe_postconditions = [
        clause
        for clause in spec.postconditions
        if not _clause_references_undeclared_helper(clause, declared)
    ]
    ensures = _join_contracts(safe_postconditions)
    default_value = _default_literal(return_type)
    return "\n".join(
        [
            f"trusted atom {_safe_identifier(spec.function_name)}({params}) -> {return_type} {{",
            f"    requires: {requires};",
            f"    ensures: {ensures};",
            "    body: {",
            f"        {default_value}",
            "    }",
            "}",
        ]
    )

def _python_args(args: ast.arguments) -> Iterable[ast.arg]:
    return [*args.posonlyargs, *args.args, *args.kwonlyargs]

def _line_for_offset(source: str, offset: int) -> int:
    return source[:offset].count("\n") + 1

def _python_type(annotation: ast.expr | None) -> str:
    if annotation is None:
        return "i64"
    try:
        return _mumei_type(ast.unparse(annotation))
    except ValueError:
        return "i64"

def _typescript_params(params_text: str) -> dict[str, str]:
    params: dict[str, str] = {}
    for index, raw in enumerate(_split_params(params_text)):
        raw = raw.strip()
        if not raw:
            continue
        raw = raw.split("=", 1)[0].strip()
        raw = raw.removeprefix("readonly ").strip()
        name_text, _, type_text = raw.partition(":")
        name = _safe_identifier(name_text.strip().rstrip("?") or f"arg{index}")
        params[name] = _typescript_type(type_text.strip() or "number")
    return params

def _rust_params(params_text: str) -> dict[str, str]:
    params: dict[str, str] = {}
    for index, raw in enumerate(_split_params(params_text)):
        raw = raw.strip()
        if raw in {"self", "&self", "&mut self", "mut self"}:
            continue
        name_text, _, type_text = raw.partition(":")
        name_text = name_text.strip().removeprefix("mut ").strip()
        name = _safe_identifier(name_text or f"arg{index}")
        params[name] = _rust_type(type_text.strip() or "i64")
    return params

def _go_params(params_text: str) -> dict[str, str]:
    params: dict[str, str] = {}
    for index, raw in enumerate(_split_params(params_text)):
        raw = raw.strip()
        if not raw:
            continue
        pieces = raw.split()
        if len(pieces) >= 2:
            name_text, type_text = pieces[0], pieces[-1]
        else:
            name_text, type_text = raw, "int"
        params[_safe_identifier(name_text or f"arg{index}")] = _go_type(type_text)
    return params

def _clean_jsdoc(comment: str) -> str:
    lines: list[str] = []
    for line in comment.splitlines():
        stripped = line.strip()
        stripped = stripped.removeprefix("/**").removesuffix("*/").strip()
        stripped = stripped.removeprefix("*").strip()
        if stripped:
            lines.append(stripped)
    return "\n".join(lines)

def _preceding_jsdoc(source: str, declaration_start: int) -> str:
    prefix = source[:declaration_start]
    comment_start = prefix.rfind("/**")
    comment_end = prefix.rfind("*/")
    if comment_start == -1 or comment_end == -1 or comment_end < comment_start:
        return ""
    comment_end += 2
    if prefix[comment_end:].strip():
        return ""
    return prefix[comment_start:comment_end]

def _clean_rust_doc(comment: str) -> str:
    lines: list[str] = []
    for line in comment.splitlines():
        stripped = line.strip()
        if stripped.startswith("///"):
            stripped = stripped[3:].strip()
        if stripped:
            lines.append(stripped)
    return "\n".join(lines)

def _clean_go_doc(comment: str) -> str:
    lines: list[str] = []
    for line in comment.splitlines():
        stripped = line.strip()
        if stripped.startswith("//"):
            stripped = stripped[2:].strip()
        if stripped:
            lines.append(stripped)
    return "\n".join(lines)

def _contract_lines(text: str) -> tuple[list[str], list[str]]:
    preconditions: list[str] = []
    postconditions: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip().lstrip("-").strip()
        lower = line.lower()
        target: list[str] | None = None
        marker = ""
        for prefix in ("@requires", "@pre", "requires:", "precondition:", "preconditions:"):
            if lower.startswith(prefix):
                target = preconditions
                marker = prefix
                break
        if target is None:
            for prefix in ("@ensures", "@post", "ensures:", "postcondition:", "postconditions:"):
                if lower.startswith(prefix):
                    target = postconditions
                    marker = prefix
                    break
        if target is not None:
            value = _strip_contract_marker(line, marker)
            # Human-language contracts such as ``X returns true`` are not
            # boolean Mumei expressions and would fail spec lowering.
            if re.search(r"\breturns\b", value):
                value = "true"
            # Natural-language preconditions (``the maps are populated``) are not
            # valid Mumei expressions; treat them as an unannotated contract.
            if re.search(
                r"\b(?:the|are|is|must|shall|populated|present|defined|maps?)\b",
                value,
                flags=re.IGNORECASE,
            ):
                value = "true"
            target.append(value)
    return preconditions, postconditions

def _strip_contract_marker(line: str, marker: str) -> str:
    value = line[len(marker) :].strip()
    value = value.lstrip(":").strip().rstrip(".")
    return value or "true"

def _join_contracts(contracts: list[str]) -> str:
    cleaned = [contract.strip().rstrip(";") for contract in contracts if contract.strip()]
    return " && ".join(cleaned) if cleaned else "true"

def _python_type_name(type_name: str) -> str:
    return type_name.replace("typing.", "").replace("builtins.", "")

def _typescript_type(type_name: str) -> str:
    normalized = type_name.strip().split("|", 1)[0].strip()
    normalized = re.sub(r"\s+", " ", normalized)
    return _mumei_type(normalized)

def _rust_type(type_name: str) -> str:
    normalized = type_name.strip().lstrip("&").removeprefix("mut ").strip()
    return _mumei_type(normalized)

def _go_type(type_name: str) -> str:
    return _mumei_type(type_name.strip().lstrip("*"))

def _solidity_type(type_name: str) -> str:
    normalized = type_name.strip().removesuffix("[]")
    for modifier in ("memory", "calldata", "storage", "payable"):
        normalized = normalized.replace(modifier, "").strip()
    # Solidity declarations may include a parameter name (``bool flag``); keep only the type.
    if normalized and " " in normalized:
        normalized = normalized.split()[0]
    lowered = normalized.lower()
    if lowered.startswith("uint"):
        return "u64"
    if lowered.startswith("int"):
        return "i64"
    if lowered == "bool":
        return "bool"
    if lowered in {"string", "bytes"}:
        return "string"
    if lowered == "address":
        return "i64"
    return _mumei_type(normalized)

def _solidity_params(params_text: str) -> dict[str, str]:
    params: dict[str, str] = {}
    modifiers = {"memory", "calldata", "storage", "payable", "indexed"}
    for index, raw in enumerate(_split_params(params_text)):
        raw = raw.strip()
        if not raw:
            continue
        tokens = [token for token in raw.split() if token.lower() not in modifiers]
        if len(tokens) >= 2:
            type_text, name_text = tokens[0], tokens[-1]
        elif tokens:
            type_text, name_text = tokens[0], f"arg{index}"
        else:
            continue
        params[_safe_identifier(name_text)] = _solidity_type(type_text)
    return params

_BYTE_LIKE_TYPE_RE = re.compile(
    r"^(?:"
    r"\[\](?:byte|uint8)"  # Go []byte / []uint8
    r"|vec<\s*u8\s*>"  # Rust Vec<u8>
    r"|\[\s*u8\s*(?:;[^\]]*)?\]"  # Rust [u8] / [u8; N]
    r"|uint8array|arraybuffer|buffer"  # TS Uint8Array / ArrayBuffer / Buffer
    r"|bytes\d*"  # Solidity/general bytes, bytes32
    r")$"
)


def _mumei_type(type_name: str) -> str:
    normalized = _python_type_name(type_name).strip()
    normalized = normalized.removeprefix("Promise<").removesuffix(">")
    normalized = normalized.strip()
    byte_probe = _python_type_name(type_name).replace(" ", "").lstrip("&").lower()
    if byte_probe.startswith("promise<") and byte_probe.endswith(">"):
        byte_probe = byte_probe[len("promise<") : -1]
    if _BYTE_LIKE_TYPE_RE.match(byte_probe):
        # Byte slices / arrays / buffers are modeled as opaque strings rather
        # than defaulting to i64, mirroring the Solidity bytes->string
        # convention, so migration skeletons keep type fidelity (#283).
        return "string"
    normalized = normalized.removesuffix("[]").strip()
    normalized_lower = normalized.lower()
    if normalized_lower in {"int", "integer", "number", "i8", "i16", "i32", "i64", "isize"}:
        return "i64"
    if normalized_lower in {"uint", "usize", "u8", "u16", "u32", "u64"}:
        return "u64"
    if normalized_lower in {"float", "double", "f32", "f64"}:
        return "f64"
    if normalized_lower in {"bool", "boolean"}:
        return "bool"
    if normalized_lower in {"str", "string", "String".lower(), "&str"}:
        return "string"
    if normalized_lower in {"none", "void", "unit", "()"}:
        return "bool"
    return "i64"

def _default_literal(type_name: str) -> str:
    normalized = type_name.strip().lower()
    if normalized in {"bool", "boolean"}:
        return "true"
    if normalized in {"str", "string"}:
        return '""'
    if normalized == "f64":
        return "0.0"
    if normalized in {"()", "void", "unit", "none", "nonetype"}:
        return "()"
    return "0"

_MUMEI_RESERVED_IDENTIFIERS = {
    "call",
}


def _safe_identifier(value: str) -> str:
    safe = re.sub(r"\W+", "_", value.strip())
    safe = safe.strip("_")
    if not safe:
        return "foreign_code_atom"
    if safe[0].isdigit():
        return f"atom_{safe}"
    if safe in _MUMEI_RESERVED_IDENTIFIERS:
        return f"{safe}_"
    return safe

def _normalize_language(language: str) -> str:
    aliases = {
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
    return aliases.get(language.strip().lower(), language.strip().lower())

def _is_generated_source(source: str) -> bool:
    """Return True when ``source`` starts with a standard generated-code marker."""
    return bool(re.search(r"^\s*//\s*Code generated by", source, re.MULTILINE))


def _is_go_test_helper(source: str) -> bool:
    """Return True for Go test-helper files (package test/testing with t *testing.T)."""
    return bool(re.search(r"^\s*func\s+\w+\s*\(\s*t\s+\*?testing\.(?:T|TB)\b", source, re.MULTILINE))


def _detect_safety_issues(
    source: str, language: str, source_file: str | None = None
) -> list[ForeignSafetyIssue]:
    if _is_generated_source(source):
        return []
    normalized = _normalize_language(language)
    original_source = source
    if normalized == "rust":
        # Function boundaries come from tree-sitter (or the regex fallback,
        # which strips literals/comments itself); ``_detect_block_safety_issues``
        # re-strips each body before the regex safety heuristics run. Declared
        # ``const`` values are collected so a non-zero constant divisor/index is
        # not modeled as a free integer (#296, generalized across languages).
        blocks = _rust_function_blocks(source)
        issues = _detect_block_safety_issues(
            source,
            blocks,
            "Rust",
            known_constants=semantic_safety.collect_declared_constants(source, "rust"),
        )
        # Suppress false positives for ``(param - N) as usize`` indexing into
        # ``const`` arrays (e.g. ``LAST_DAYS[(month - 1) as usize]``).  The tool
        # lacks the caller range contract, so the cast is unprovable.
        return [
            issue
            for issue in issues
            if not _is_rust_usize_cast_array_issue(issue, source, blocks)
        ]
    if normalized == "typescript":
        blocks = _typescript_function_blocks(source)
        nullable_params = _typescript_nullable_param_names(source)
        return _detect_block_safety_issues(
            source,
            blocks,
            "TypeScript",
            known_constants=semantic_safety.collect_declared_constants(
                source, "typescript"
            ),
            nullable_params=nullable_params,
        )
    if normalized == "go":
        if (
            _is_go_compiler_test(source)
            or _is_go_experimental(source)
            or _is_go_test_helper(source)
            or (source_file is not None and source_file.endswith("_test.go"))
            or (
                source_file is not None
                and re.search(r"(?:^|[/\\])go[/\\]test[/\\]", source_file) is not None
            )
            or (
                source_file is not None
                and re.search(r"(?:^|[/\\])testdata[/\\]", source_file) is not None
            )
        ):
            return []
        package_source = _go_package_source(source, source_file)
        known_constants = _go_declared_constants(package_source)
        stripped_source = _strip_go_rust_literals_and_comments(source)
        return _detect_go_safety_issues(stripped_source, known_constants=known_constants, original_source=original_source, source_file=source_file)
    if normalized == "python":
        return _detect_python_safety_issues(source)
    if normalized == "solidity":
        mapping_names = _solidity_mapping_names(source)
        issues = _detect_block_safety_issues(
            source,
            _solidity_function_blocks(source),
            "Solidity",
            known_constants=_solidity_declared_constants(source),
            mapping_names=mapping_names,
            guaranteed_nonzero=_solidity_guaranteed_nonzero_params(source),
        )
        issues.extend(_detect_solidity_contract_issues(source, source_file=source_file))
        return issues
    return []


def _solidity_mapping_names(source: str) -> set[str]:
    """Return the set of state-variable names declared as Solidity ``mapping`` types.

    Mapping key access is always safe (a missing key returns the type's zero
    value), so bounds contracts on mapping indices are false positives.
    """
    names: set[str] = set()
    # ``mapping(KeyType => ValueType) visibility name;`` possibly with nested
    # single-level parentheses inside the value type.
    pattern = re.compile(
        r"\bmapping\s*\((?:[^()]|\([^()]*\))*\)\s*(?:[A-Za-z_][\w]*\s+)*([A-Za-z_][\w]*)\s*[;=]",
        re.DOTALL,
    )
    for match in pattern.finditer(source):
        names.add(match.group(1))
    return names


def _evaluate_solidity_constant_expression(expr: str, constants: dict[str, int]) -> int | None:
    """Safely evaluate a Solidity constant arithmetic expression.

    Supports ``+``, ``-``, ``*``, ``/``, ``**``, parentheses, integer literals
    (decimal/hex/binary/octal), and references to already-known constants.
    """
    expr = expr.strip()
    if not expr:
        return None
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return None

    def _eval(node: ast.AST) -> int | None:
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, int):
                return node.value
            return None
        if isinstance(node, ast.Name):
            return constants.get(node.id)
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
            if isinstance(node.op, ast.Div):
                if right == 0:
                    return None
                return left // right
            if isinstance(node.op, ast.FloorDiv):
                if right == 0:
                    return None
                return left // right
            if isinstance(node.op, ast.Pow):
                if right < 0 or right > 1024:
                    return None
                result = left ** right
                return result if isinstance(result, int) else None
            return None
        if isinstance(node, ast.UnaryOp):
            operand = _eval(node.operand)
            if operand is None:
                return None
            if isinstance(node.op, ast.UAdd):
                return +operand
            if isinstance(node.op, ast.USub):
                return -operand
            return None
        return None

    return _eval(tree)


def _solidity_declared_constants(source: str) -> dict[str, int]:
    """Map Solidity ``constant``/``immutable`` names to their integer value.

    Resolves arithmetic expressions of already-known constants so that
    composite constants such as ``NEXT_OFFSET = ADDR_SIZE + FEE_SIZE`` are
    treated as concrete non-zero values rather than free Z3 integers (#296).
    """
    constants: dict[str, int] = {}
    pattern = re.compile(
        r"\b(?:u?int\d*|address|bytes\d*|bool)\s+"
        r"(?:(?:public|private|internal|external)\s+)*"
        r"(?:constant|immutable)\s+"
        r"(?P<name>[A-Za-z_]\w*)\s*=\s*(?P<value>[^;]+);"
    )
    changed = True
    while changed:
        changed = False
        for match in pattern.finditer(source):
            name = match.group("name")
            if name in constants:
                continue
            value = _evaluate_solidity_constant_expression(match.group("value"), constants)
            if value is not None:
                constants[name] = value
                changed = True
    return constants


def _evaluate_go_constant_expression(
    expr: str, values: dict[str, Fraction]
) -> Fraction | None:
    """Safely evaluate a Go constant arithmetic expression.

    Supports ``+``, ``-``, ``*``, ``/``, ``<<``, ``>>``, parentheses, numeric
    literals (decimal, hex, binary, octal, float with exponent/underscores), and
    references to already-known constants.  The result is a ``Fraction`` so that
    floating-point intermediate values (e.g. ``365.2425``) stay exact until a
    final integer conversion is requested.
    """
    expr = expr.strip()
    if not expr:
        return None
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return None

    def _constant_value(node: ast.Constant) -> Fraction | None:
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
            return values.get(f"{getattr(node.value, 'id', '')}.{node.attr}")
        if isinstance(node, ast.Call):
            # Allow numeric casts such as ``int64(x)``; ignore the type.
            if (
                isinstance(node.func, ast.Name)
                and node.func.id
                in {
                    "int",
                    "int8",
                    "int16",
                    "int32",
                    "int64",
                    "uint",
                    "uint8",
                    "uint16",
                    "uint32",
                    "uint64",
                    "uintptr",
                    "float32",
                    "float64",
                    "byte",
                    "rune",
                }
                and node.args
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
                # Go integer division truncates toward zero.
                return Fraction(int(left / right))
            if isinstance(node.op, ast.Mod):
                if right == 0:
                    return None
                return Fraction(int(left) % int(right))
            if isinstance(node.op, ast.Pow):
                exp = int(right)
                if exp < 0 or exp > 64:
                    return None
                return left ** exp
            if isinstance(node.op, ast.LShift):
                return Fraction(int(left) << int(right))
            if isinstance(node.op, ast.RShift):
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
            return None
        return None

    return _eval(tree)


def _go_parse_top_level_declarations(source: str) -> list[tuple[str, str, str]]:
    """Return ``(kind, name, value)`` for top-level ``const``/``var`` declarations.

    Handles both single-line declarations and ``const (...)`` / ``var (...)``
    blocks, including balanced parenthesis scanning so nested expressions do not
    terminate a block prematurely.
    """
    decls: list[tuple[str, str, str]] = []
    # Single-line: ``const/var name = value`` or ``const/var name int = value``.
    for match in re.finditer(
        r"^\s*(const|var)\s+(\w+)\s*(?:\w+\s*)?=\s*([^;\n]+)",
        source,
        re.MULTILINE,
    ):
        value = re.sub(r"\s*//.*", "", match.group(3)).strip()
        decls.append((match.group(1), match.group(2), value))
    # Block declarations.
    i = 0
    while True:
        m = re.search(r"^\s*(const|var)\s*\(", source[i:], re.MULTILINE)
        if not m:
            break
        kind = m.group(1)
        start = i + m.end()
        depth = 1
        j = start
        while j < len(source) and depth > 0:
            if source[j] == "(":
                depth += 1
            elif source[j] == ")":
                depth -= 1
            j += 1
        block = source[start : j - 1]
        prev_value: str | None = None
        for raw_line in block.splitlines():
            line = re.sub(r"//.*", "", raw_line).strip()
            if not line:
                continue
            m2 = re.match(r"(\w+)(?:\s+\w+)?\s*(?:=\s*(.+))?$", line)
            if not m2:
                continue
            name, value = m2.group(1), m2.group(2)
            if value is None:
                if prev_value is None or not prev_value:
                    continue
                value = prev_value
            else:
                prev_value = value
            decls.append((kind, name, value.strip()))
        i = j
    return decls


def _go_package_source(
    source: str, source_file: str | None, max_chars: int = 500_000
) -> str:
    """Return ``source`` combined with sibling non-test ``.go`` files.

    Go package-level ``const``/``var`` declarations are visible across files, so
    a single-file audit needs the package context to know array sizes such as
    ``[256]encoding`` declared in a sibling file.  A size cap keeps huge packages
    such as ``cmd/compile/internal/ssa`` from slowing every audit.
    """
    if not source_file:
        return source
    path = Path(source_file)
    if not path.exists():
        return source
    # Large generated files (e.g. ``cmd/compile/internal/ssa/opGen.go``) are
    # dominated by data tables; only the first chunk is needed for constants.
    parts = [source[:max_chars]]
    total = len(parts[0])
    for sibling in sorted(path.parent.glob("*.go")):
        if sibling.name.endswith("_test.go") or sibling == path:
            continue
        try:
            text = sibling.read_text(encoding="utf-8")[:max_chars]
        except Exception:
            continue
        total += len(text)
        if total > max_chars:
            break
        parts.append(text)
    return "\n".join(parts)


def _go_declared_constants(source: str) -> dict[str, int]:
    """Map top-level Go ``const`` names to their integer literal values.

    Constants such as ``gcmStandardNonceSize = 12`` should not be modeled as
    free Z3 integers that can be chosen negative or huge, which would cause
    spurious overflow/index reports on constant-only expressions (#406).
    """
    constants: dict[str, int] = {}
    max_i64 = 9_223_372_036_854_775_807
    min_i64 = -9_223_372_036_854_775_808
    values: dict[str, Fraction] = {}
    changed = True
    while changed:
        changed = False
        for kind, name, value in _go_parse_top_level_declarations(source):
            if kind != "const" or name in values:
                continue
            evaluated = _evaluate_go_constant_expression(value, values)
            if evaluated is not None and evaluated.denominator == 1:
                int_value = int(evaluated)
                if min_i64 <= int_value <= max_i64:
                    values[name] = evaluated
                    constants[name] = int_value
                    changed = True
    # Package-level arrays with a positive literal size have a compile-time ``len``.
    for match in re.finditer(
        r"^\s*var\s+(\w+)\s*(?:=\s*)?\[\s*(\d+)\s*\]",
        source,
        re.MULTILINE,
    ):
        name, size = match.group(1), match.group(2)
        if int(size) > 0:
            constants[f"len({name})"] = int(size)
    return constants


def _go_actor_nonnil_params(
    param_types: dict[str, str],
    function_name: str = "",
    params_text: str = "",
    return_type: str | None = None,
) -> set[str]:
    """Return parameter names that are non-nil for ``Actor.Act`` implementations.

    ``go/cmd/go/internal/work.Actor`` interface methods have signature
    ``Act(*Builder, context.Context, *Action) error``. The concrete implementations
    are always invoked with non-nil ``*Builder`` and ``*Action`` values by the
    action graph executor, so nil-receiver counterexamples for those parameters are
    caller-contract noise.
    """
    if function_name != "Act":
        return set()
    if not _go_method_receiver_type(params_text or ""):
        return set()
    if return_type and "error" not in return_type:
        return set()
    nonnil: set[str] = set()
    type_by_name = {name: raw.strip() for name, raw in param_types.items()}
    values = set(type_by_name.values())
    if "*Builder" in values and "context.Context" in values and "*Action" in values:
        for name, raw in type_by_name.items():
            if raw in {"*Builder", "*Action"}:
                nonnil.add(_safe_identifier(name))
    return nonnil


def _go_nonzero_constants(source: str) -> set[str]:
    """Return top-level Go identifiers that are provably non-zero.

    Includes ``const``/``var`` initializer values and, for the ``runtime`` package,
    common non-zero sizing constants such as ``pageSize`` and ``physPageSize`` that
    are declared across multiple source files.
    """
    nonzero: set[str] = set(_go_known_nonzero_selectors(source))

    pkg_match = re.search(r"^\s*package\s+(\w+)", source, re.MULTILINE)
    if pkg_match and pkg_match.group(1) == "runtime":
        # Runtime page/summary constants are always positive; the audit is per
        # file and cannot see cross-file declarations.
        nonzero.update(
            {
                "pageSize",
                "physPageSize",
                "minPhysPageSize",
                "maxPhysPageSize",
                "heapArenaBytes",
                "pagesPerArena",
                "pagesPerReclaimerChunk",
                "pagesPerSpanRoot",
                "pallocChunkBytes",
                "pallocChunkPages",
                "summaryLevels",
                "levelBits",
                "levelLogPages",
                "traceTimeDiv",
                "minTimeForTicksPerSecond",
            }
        )

    # Seed values with known positive package constants (``time.Second`` etc.).
    values: dict[str, Fraction] = {
        "time.Nanosecond": Fraction(1),
        "time.Microsecond": Fraction(1000),
        "time.Millisecond": Fraction(1_000_000),
        "time.Second": Fraction(1_000_000_000),
        "time.Minute": Fraction(60 * 1_000_000_000),
        "time.Hour": Fraction(3600 * 1_000_000_000),
    }
    changed = True
    while changed:
        changed = False
        for kind, name, value in _go_parse_top_level_declarations(source):
            if name in values:
                continue
            evaluated = _evaluate_go_constant_expression(value, values)
            if evaluated is not None and evaluated != 0:
                values[name] = evaluated
                nonzero.add(name)
                changed = True
            elif re.fullmatch(r"\d+\s*<<\s*\w+", value):
                # ``1 << iota`` and similar repeated expressions are always non-zero
                # in a Go constant declaration (``iota`` is non-negative).  The
                # exact value is not needed for non-zero propagation; use 1 as a
                # sentinel so the fixed-point loop terminates.
                values[name] = Fraction(1)
                nonzero.add(name)
                changed = True
    return nonzero


def _go_rounded_factor_nonzero(body: str) -> set[str]:
    """Return constants used as ``math.Round(score*K) / K`` rounding factors.

    Such factors are package-level positive constants (e.g. ``ScoreRoundingFactor``),
    so division by them is safe.
    """
    factors: set[str] = set()
    for match in re.finditer(
        r"\b(?:math\.)?Round\([^)]*\*(\w+)\)[^/]*/\s*\1", body, re.DOTALL
    ):
        name = match.group(1)
        if name[0].isupper() or name.endswith("Factor"):
            factors.add(name)
    return factors


def _go_import_aliases(source: str) -> dict[str, str]:
    """Return a mapping ``{alias: package}`` for Go import declarations.

    Handles single imports ``import "time"`` and block imports. Blank imports
    and dot imports are ignored.
    """
    aliases: dict[str, str] = {}
    single = re.search(r'^\s*import\s+"([^"]+)"', source, re.MULTILINE)
    if single:
        pkg = single.group(1)
        aliases[pkg.split("/")[-1]] = pkg
    block = re.search(r'^\s*import\s*\((.*?)\)', source, re.MULTILINE | re.DOTALL)
    if block:
        for line in block.group(1).splitlines():
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            m = re.match(r'^(?:(\w+)\s+)?["\']([^"\']+)["\']', line)
            if m:
                alias, pkg = m.group(1), m.group(2)
                if alias is None:
                    alias = pkg.split("/")[-1]
                if alias != "_":
                    aliases[alias] = pkg
    return aliases


def _go_known_nonzero_selectors(source: str) -> set[str]:
    """Return package constants that are provably non-zero.

    ``time.Second`` / ``time.Minute`` etc. and ``math.Pi`` / ``math.E`` etc. are
    positive constants, so divisions by them are safe. Within the ``math`` package
    itself these constants are referenced without a qualifier.
    """
    aliases = _go_import_aliases(source)
    pkg_constants: dict[str, set[str]] = {
        "time": {"Nanosecond", "Microsecond", "Millisecond", "Second", "Minute", "Hour"},
        "math": {
            "Pi", "E", "Phi", "Sqrt2", "SqrtPi", "SqrtE", "Ln2", "Log2E",
            "MaxFloat32", "SmallestNonzeroFloat32", "MaxFloat64", "SmallestNonzeroFloat64",
        },
    }
    nonzero: set[str] = set()
    for alias, pkg in aliases.items():
        for const in pkg_constants.get(pkg, set()):
            nonzero.add(f"{alias}.{const}")
    # Inside the ``math`` package itself, these constants are unqualified.
    if _go_package_name(source) == "math":
        nonzero.update(pkg_constants.get("math", set()))
    return nonzero


def _go_beacon_config_nonzero_locals(body: str, source: str) -> set[str]:
    """Return local variables assigned from ``params.BeaconConfig().*``.

    Prysm/config fields and methods such as ``MaxBlobsPerBlock`` and
    ``DataColumnSidecarSubnetCount`` are protocol constants and are never zero,
    so divisions by them are safe.
    """
    aliases = _go_import_aliases(source)
    params_aliases = {
        alias for alias, pkg in aliases.items()
        if pkg == "params" or pkg.endswith("/params")
    }
    if not params_aliases:
        return set()
    alias_re = "|".join(re.escape(a) for a in params_aliases)
    locals: set[str] = set()
    for match in re.finditer(
        rf"\b(\w+)\s*:?=\s*(?:\w+\s*\(\s*)?({alias_re})\.BeaconConfig\(\)\.(\w+)(?:\s*\([^)]*\))?\b",
        body,
    ):
        locals.add(match.group(1))
    return locals


def _go_expression_is_float(expression: str, float_vars: set[str]) -> bool:
    """Heuristic: is ``expression`` a Go floating-point expression?"""
    text = _strip_go_rust_literals_and_comments(expression)
    # Explicit float conversion or float literal.
    if re.search(r"\b(?:float64|float32)\s*\(", text):
        return True
    if re.search(r"\b\d+\.\d+(?:[eE][-+]?\d+)?\b|\b\d+[eE][-+]?\d+\b", text):
        return True
    # If any top-level operand is already float, the whole expression is float.
    func_re = rf"\b(?:{'|'.join(_GO_FLOAT_FUNCTIONS)})\s*\("
    for part in _split_top_level_operators(text, ("+", "-", "*", "/", "%")):
        part = part.strip().lstrip("-").strip()
        if not part:
            continue
        if re.search(r"\b(?:float64|float32)\s*\(", part):
            return True
        if re.search(r"\b\d+\.\d+(?:[eE][-+]?\d+)?\b|\b\d+[eE][-+]?\d+\b", part):
            return True
        if re.search(func_re, part):
            return True
        # An operand that is a single known float variable is enough.
        if part in float_vars:
            return True
    return False


def _go_float_variables(body: str, param_float_vars: set[str] | None = None) -> set[str]:
    """Return local variable names that are initialized with floating-point values."""
    float_vars = set(param_float_vars or set())
    changed = True
    while changed:
        changed = False
        for match in re.finditer(
            r"^\s*(\w+)\s*:=\s*([^;\n]+)$", body, re.MULTILINE
        ):
            name, rhs = match.group(1), match.group(2).strip()
            if name in float_vars:
                continue
            if _go_expression_is_float(rhs, float_vars):
                float_vars.add(name)
                changed = True
    return float_vars


def _go_float_param_names(params_text: str) -> set[str]:
    """Return parameter names whose declared type is ``float32`` or ``float64``."""
    return {
        name
        for name, raw_type in _go_param_types(params_text).items()
        if raw_type.strip().lstrip("*").lower() in {"float32", "float64"}
    }


def _go_float_casts(expression: str) -> set[str]:
    """Return source snippets of explicit ``float32(...)`` / ``float64(...)`` casts.

    Go float division by zero is well-defined (produces +/-Inf or NaN), so
    these cast expressions should not be reported as integer divide-by-zero.
    """
    return set(re.findall(r"\b(?:float32|float64)\s*\([^()]*\)", expression))


_RUST_FLOAT_METHODS = (
    "round|floor|ceil|sqrt|powf|exp|ln|log|log2|log10|sin|cos|tan|"
    "asin|acos|atan|atan2|sinh|cosh|tanh|trunc|fract|recip|"
    "to_degrees|to_radians|mul_add"
)


def _rust_expression_is_float(expression: str, float_vars: set[str]) -> bool:
    """Heuristic: is ``expression`` a Rust floating-point expression?"""
    text = _strip_go_rust_literals_and_comments(expression)
    # Float literal (e.g. 100.0, 10_000.0, 1e9).
    if re.search(r"\b\d[\d_]*\.\d[\d_]*(?:[eE][-+]?\d+)?\b|\b\d[\d_]*[eE][-+]?\d+\b", text):
        return True
    # Explicit cast to a float type.
    if re.search(r"\b(?:as\s+(?:f32|f64)|f32::|f64::)\b", text):
        return True
    # num::cast of a float literal or a known float variable.
    for match in re.finditer(r"\bnum::cast\s*\(\s*([^)]+)\s*\)", text):
        arg = match.group(1).strip()
        if arg in float_vars:
            return True
        if re.search(r"\b\d[\d_]*\.\d[\d_]*(?:[eE][-+]?\d+)?\b|\b\d[\d_]*[eE][-+]?\d+\b", arg):
            return True
    # Known float-returning method calls such as `.round()`.
    if re.search(r"\.\s*(?:" + _RUST_FLOAT_METHODS + r")\s*\(", text):
        return True
    # The whole expression is a known float variable.
    if text.strip() in float_vars:
        return True
    return False


def _rust_float_variables(body: str) -> set[str]:
    """Return local variable names that are initialized with floating-point values."""
    body = _strip_go_rust_literals_and_comments(body)
    float_vars: set[str] = set()
    changed = True
    while changed:
        changed = False
        for match in re.finditer(
            r"let\s+(?:mut\s+)?(\w+)\s*(?::\s*[\w<>,\s]+)?\s*=\s*([^;]+);",
            body,
            re.DOTALL,
        ):
            name, rhs = match.group(1), match.group(2).strip()
            if name in float_vars:
                continue
            if _rust_expression_is_float(rhs, float_vars):
                float_vars.add(name)
                changed = True
    return float_vars


_RUST_UNSIGNED_TYPES = {"usize", "u64", "u32", "u16", "u8"}


def _rust_unsigned_variables(source: str, body: str, function_name: str) -> set[str]:
    """Return Rust variable names that are known to have an unsigned integer type."""
    stripped = _strip_go_rust_literals_and_comments(source)
    unsigned: set[str] = set()
    # Parameters declared with an unsigned type in the function signature.
    sig_pattern = re.compile(
        r"(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+"
        + re.escape(function_name)
        + r"\s*(?:<[^>]+>)?\s*\((?P<params>[^)]*)\)"
    )
    sig_match = sig_pattern.search(stripped)
    if sig_match:
        for param_match in re.finditer(
            r"(?P<name>[A-Za-z_]\w*)\s*:\s*(?P<type>[^,=]+)",
            sig_match.group("params"),
        ):
            raw_type = param_match.group("type").strip().removeprefix("&mut ").removeprefix("&")
            if re.sub(r"\s+", "", raw_type).lower() in _RUST_UNSIGNED_TYPES:
                unsigned.add(param_match.group("name"))

    body_stripped = _strip_go_rust_literals_and_comments(body)
    changed = True
    while changed:
        changed = False
        for match in re.finditer(
            r"let\s+(?:mut\s+)?(?P<name>\w+)\s*(?::\s*(?P<typ>[^;=]+))?\s*=\s*(?P<rhs>[^;]+);",
            body_stripped,
            re.DOTALL,
        ):
            name = match.group("name")
            if name in unsigned:
                continue
            typ = (match.group("typ") or "").strip()
            if typ:
                raw_type = typ.removeprefix("&mut ").removeprefix("&")
                if re.sub(r"\s+", "", raw_type).lower() in _RUST_UNSIGNED_TYPES:
                    unsigned.add(name)
                    changed = True
                    continue
            rhs = match.group("rhs").strip()
            # Assigned from an atomic fetch operation (returns the previous unsigned value).
            if re.search(r"\.\s*fetch_[a-z]+\s*\(", rhs):
                unsigned.add(name)
                changed = True
                continue
            # Assigned from another known-unsigned identifier.
            if re.fullmatch(r"[A-Za-z_]\w*", rhs) and rhs in unsigned:
                unsigned.add(name)
                changed = True
        # Closure parameters used in an addition with a known-unsigned operand.
        for match in re.finditer(
            r"\|\s*(?P<param>\w+)\s*\|\s*(?P<body>[^;\n]+)",
            body_stripped,
        ):
            param = match.group("param")
            if param in unsigned:
                continue
            closure_body = match.group("body")
            for um in re.finditer(
                r"\b(?P<left>\w+)\s*\+\s*(?P<right>\w+)\b",
                closure_body,
            ):
                left, right = um.group("left"), um.group("right")
                if (left == param and right in unsigned) or (right == param and left in unsigned):
                    unsigned.add(param)
                    changed = True
                    break
    return unsigned


def _rust_guarded_indices(body: str) -> set[str]:
    """Return Rust local variable names that are bounded by ``% .len()``.

    Patterns such as ``let index = (time / 70) % frames.len();`` ensure
    ``0 <= index < len(frames)``, so any subsequent ``frames[index]`` is safe.
    """
    guarded: set[str] = set()
    body = _strip_go_rust_literals_and_comments(body)
    # ``let index = ... % container.len();``  or ``... % (container.len());``
    pattern = re.compile(
        r"let\s+(?:mut\s+)?(\w+)\s*(?::\s*[\w<>,\s]+)?\s*=\s*([^;]+)\s*;",
        re.DOTALL,
    )
    for match in pattern.finditer(body):
        name, rhs = match.group(1), match.group(2)
        if re.search(r"%\s*[A-Za-z_]\w*\.\s*len\s*\(\s*\)", rhs):
            guarded.add(name)
    return guarded


def _rust_doc_comment_nonzero_params(source: str, name: str) -> set[str]:
    """Extract parameter names whose doc comment states they must be non-zero.

    Matches Rust doc comments such as:
    ``If `num_buckets` is zero, this will panic.`` or
    ``num_buckets MUST be non-zero.``
    """
    params: set[str] = set()
    # Find the function and its preceding doc comment block.
    for match in re.finditer(
        r"(?P<doc>(?:[ \t]*///[^\n]*\n(?:[ \t]*///[^\n]*\n)*\s*)?)"
        r"(?P<attrs>(?:\s*#\s*\[[^\]]*\]\s*)*)"
        r"(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+"
        + re.escape(name)
        + r"\b",
        source,
        re.DOTALL,
    ):
        doc = match.group("doc") or ""
        patterns = [
            r"If\s+[`']?(\w+)[`']?\s+is\s+(?:zero|0)[^\.]*panic",
            r"[`']?(\w+)[`']?\s*(?:==|is)\s*(?:zero|0)[^\.]*panic",
            r"(\w+)\s+MUST\s+be\s+(?:non-zero|nonzero|positive|greater than zero)",
            r"(\w+)\s+must\s+not\s+be\s+(?:zero|0)",
            r"Panics[^\.]*if\s+[`']?(\w+)[`']?\s+is\s+(?:zero|0)",
        ]
        for pat in patterns:
            for m in re.finditer(pat, doc, re.IGNORECASE):
                for group in m.groups():
                    if group:
                        params.add(group)
                        break
    return params


def _go_scale_nonzero_params(name: str, params_text: str) -> set[str]:
    """Return ``scale`` parameter names for scaling functions as guaranteed non-zero.

    Functions whose name contains ``scale``/``scaled`` operate on a scaling
    factor; a zero scale would be a caller bug, so we treat the ``scale``
    parameter as guaranteed non-zero to avoid divide-by-zero false positives
    (e.g. ``isScaledImmI(imm, nbits, scale int64)`` doing ``imm%scale``).
    """
    if not re.search(r"scale", name, re.IGNORECASE):
        return set()
    int_types = {
        "int", "int8", "int16", "int32", "int64",
        "uint", "uint8", "uint16", "uint32", "uint64", "uintptr",
        "byte", "rune",
    }
    return {
        param_name
        for param_name, param_type in _go_param_types(params_text).items()
        if param_name.lower() == "scale" and param_type.strip().lstrip("*").lower() in int_types
    }


def _go_time_interval_nonzero_params(name: str, params_text: str) -> set[str]:
    """Return time-interval parameter names as guaranteed non-zero for interval math.

    Functions named around ``interval``/``period``/``rate`` operate on a positive
    time quantum; a zero divisor would be a caller bug (e.g.
    ``intervalNumber(t, seconds int64)`` doing ``t.Unix() / seconds``).
    """
    # Require the keyword to be a distinct camel/underscore word, not a substring
    # of an unrelated identifier (e.g. ``migrate``, ``generate``, ``aggregate``).
    # ``(?i:...)`` makes the keyword case-insensitive while the surrounding
    # boundaries remain case-sensitive so ``IntervalNumber`` matches but
    # ``getRate`` and ``migrate`` do not.
    if not re.search(
        r"(?<![a-zA-Z])(?i:interval|period|rate)(?![a-z])",
        name,
    ):
        return set()
    int_types = {
        "int", "int8", "int16", "int32", "int64",
        "uint", "uint8", "uint16", "uint32", "uint64", "uintptr",
        "byte", "rune",
    }
    interval_params = {"seconds", "period", "interval", "duration", "rate", "tick"}
    return {
        param_name
        for param_name, param_type in _go_param_types(params_text).items()
        if param_name.lower() in interval_params
        and param_type.strip().lstrip("*").lower() in int_types
    }


def _go_zero_guarded_nonzero_params(body: str, param_names: set[str]) -> set[str]:
    """Return parameters guarded by an ``if x == 0 { return }`` early return.

    Code after ``if x == 0 { return ... }`` executes only when ``x != 0``,
    so a subsequent division by ``x`` is safe. Also handles ``x <= 0`` guards,
    which imply ``x > 0`` after the return.
    """
    stripped = _strip_go_rust_literals_and_comments(body)
    guarded: set[str] = set()
    for param in param_names:
        for match in re.finditer(
            rf"\bif\s+(?:[^;{{]*\b{re.escape(param)}\s*(?:<=|==)\s*0[^;{{]*)\s*{{",
            stripped,
        ):
            i = match.end()
            depth = 1
            block_start = i
            while i < len(stripped) and depth > 0:
                if stripped[i] == "{":
                    depth += 1
                elif stripped[i] == "}":
                    depth -= 1
                i += 1
            if depth == 0 and re.search(r"\b(?:return|panic)\b", stripped[block_start : i - 1]):
                guarded.add(param)
    return guarded


def _go_loop_count_nonzero_params(body: str, param_names: set[str]) -> set[str]:
    """Return parameters used as the upper bound of a positive ``for`` loop.

    A parameter ``n`` in ``for i := 0; i < n; i++`` is a repetition count; if
    it is also used as a divisor later, the intended contract is ``n > 0``.
    """
    stripped = _strip_go_rust_literals_and_comments(body)
    return {
        param
        for param in param_names
        if re.search(
            rf"\bfor\s+\w+\s*:=\s*0\s*;\s*\w+\s*<\s*{re.escape(param)}\s*;\s*\w+\+\+",
            stripped,
        )
        and re.search(
            rf"(?:/|%)\s*(?:[A-Za-z_]\w*\s*\(\s*)?{re.escape(param)}\b",
            stripped,
        )
    }


def _go_local_nonzero_variables(body: str) -> set[str]:
    """Return local Go variables that are always assigned a nonzero literal.

    For example, in ``sum := 32; if prefix == 2 { sum = 16 }``, ``sum`` is
    nonzero in every assignment and is therefore safe as a divisor/modulus.
    """
    stripped = _strip_go_rust_literals_and_comments(body)
    assignments: dict[str, list[str]] = {}
    # ``var x T`` or ``var x = expr`` declarations.
    for match in re.finditer(
        r"\bvar\s+(\w+)(?:\s+\w+)?(?:\s*=\s*([^;\n]+?))?(?:;|\n|$)", stripped
    ):
        name, value = match.group(1), match.group(2)
        assignments.setdefault(name, [])
        if value is not None:
            assignments[name].append(value.strip())
    for match in re.finditer(
        r"\b(\w+)\s*:=\s*([^;\n]+?)(?:;|\n|$)", stripped
    ):
        name, value = match.group(1), match.group(2).strip()
        assignments.setdefault(name, []).append(value)
    for match in re.finditer(
        r"\b(\w+)\s*=\s*([^;\n]+?)(?:;|\n|$)", stripped
    ):
        name, value = match.group(1), match.group(2).strip()
        if name in assignments:
            assignments[name].append(value)

    def _is_nonzero_literal_or_expr(value: str) -> bool:
        text = _strip_go_rust_literals_and_comments(value).strip()
        parsed = semantic_safety.parse_int_literal(text)
        if parsed is not None:
            return parsed != 0
        try:
            return float(text) != 0.0
        except ValueError:
            return False

    return {
        name
        for name, values in assignments.items()
        if values and all(_is_nonzero_literal_or_expr(v) for v in values)
    }


def _go_align_nonzero_params(body: str) -> set[str]:
    """Return alignment parameters that are provably non-zero.

    The standard round-up idiom ``y := x + a - 1; return y - y % a`` (or the
    equivalent bitwise form) computes an aligned offset. The alignment ``a``
    is positive by contract, so the division/modulo is safe.
    """
    stripped = _strip_go_rust_literals_and_comments(body)
    # ``y := x + a - 1`` followed by ``return y - y % a``.
    for m in re.finditer(r"\b(\w+)\s*:=\s*(\w+)\s*\+\s*(\w+)\s*-\s*1\b", stripped):
        var, base, align = m.group(1), m.group(2), m.group(3)
        if re.search(rf"\breturn\s+{re.escape(var)}\s*-\s*{re.escape(var)}\s*%\s*{re.escape(align)}\b", stripped):
            return {align}
    # Bitwise equivalent: ``return (x + a - 1) &^ (a - 1)``.
    for m in re.finditer(r"\breturn\s*\(\s*(\w+)\s*\+\s*(\w+)\s*-\s*1\s*\)\s*&\^\s*\(\s*\2\s*-\s*1\s*\)", stripped):
        return {m.group(2)}
    return set()


def _go_math_denom_nonzero_locals(body: str, source: str) -> set[str]:
    """In the ``math`` package, a local ``s := 1 + z*(...)`` is a nonzero denominator.

    The ``math`` package uses rational polynomial approximations of the form
    ``r/s`` where ``s = 1 + z*P(z)`` and ``z`` is a positive power of ``x``.
    These denominators are constructed to be nonzero in the domain.
    """
    if _go_package_name(source) != "math":
        return set()
    stripped = _strip_go_rust_literals_and_comments(body)
    nonzero: set[str] = set()
    for match in re.finditer(r"\b(\w+)\s*:=\s*1\s*\+\s*\w+\s*\*\s*\(", stripped):
        name = match.group(1)
        if re.search(rf"/\s*{re.escape(name)}\b", stripped):
            nonzero.add(name)
    return nonzero


def _go_enum_string_array_guarded_indices(
    body: str, function_name: str, receiver_name: str | None, source: str
) -> set[str]:
    """Guard the receiver in enum ``String()`` methods that index a package-level string array.

    Methods such as ``func (kind ObjKind) String() string { return objKindStrings[kind] }``
    are generated for enum-like types and are only invoked with valid enum values.
    """
    if function_name != "String" or not receiver_name:
        return set()
    stripped = _strip_go_rust_literals_and_comments(body)
    m = re.search(
        rf"\breturn\s+([A-Za-z_][A-Za-z0-9_]*)\s*\[\s*{re.escape(receiver_name)}\s*\]",
        stripped,
    )
    if not m:
        return set()
    array_name = m.group(1)
    if array_name in _go_global_array_keys(source):
        return {receiver_name}
    # Also allow package-level ``[...]string{...}`` literal (possibly non-keyed).
    if re.search(
        rf"\bvar\s+{re.escape(array_name)}\s*=\s*\[\.\.\.\]\w+\s*\{{",
        source,
    ):
        return {receiver_name}
    return set()


def _go_enum_string_guarded_indices(
    body: str, function_name: str, receiver_name: str | None
) -> set[str]:
    """Return the receiver for an enum ``String`` method with a guarded local array.

    A method such as::

        func (s RequestStatus) String() string {
            names := [...]string{"ok", "cancelled", "error"}
            if s < RequestStatusOK || s > RequestStatusError { return "" }
            return names[s]
        }

    is guarded by the range check against the enum constants, so the index is safe.
    """
    if function_name != "String" or not receiver_name:
        return set()
    stripped = _strip_go_rust_literals_and_comments(body)
    # Local array declared with an inferred or explicit positive size.
    for m in re.finditer(
        r"\b(\w+)\s*:=\s*\[(?:\.\.\.|\d+)\][\w\[\]]*\{([^}]*)\}", stripped
    ):
        arr, elems = m.group(1), m.group(2)
        if not elems.strip():
            continue
        size = elems.count(",") + 1
        # Guard of the form ``if s < ConstA || s > ConstB { return ... }``.
        guard = re.search(
            rf"\bif\s+{re.escape(receiver_name)}\s*<\s*\w+\s*\|\|\s*{re.escape(receiver_name)}\s*>\s*\w+\s*\{{[^}}]*\breturn\b",
            stripped,
        )
        if not guard:
            continue
        if re.search(
            rf"\breturn\s+{re.escape(arr)}\s*\[\s*{re.escape(receiver_name)}\s*\]",
            stripped,
        ):
            return {receiver_name}
    # Package-level lookup table: ``if ConstMin <= r && r <= ConstMax { return arr[r] }``.
    if re.search(
        rf"\bif\s+\w+\s*<=\s*{re.escape(receiver_name)}\s*&&\s*{re.escape(receiver_name)}\s*<=\s*\w+\s*\{{",
        stripped,
    ) and re.search(
        rf"\breturn\s+\w+\s*\[\s*{re.escape(receiver_name)}\s*\]",
        stripped,
    ):
        return {receiver_name}
    return set()


def _go_div_nonzero_params(name: str, params_text: str) -> set[str]:
    """Return the integer divisor parameter for functions named ``Div``/``Mod``/``Rem`` as non-zero.

    A function/method named ``Div``, ``Mod``, or ``Rem`` (with an optional bit-size
    suffix), or a runtime helper such as ``uint64div``/``int64mod``, performs
    integer division or modulo and therefore implies the divisor must be non-zero;
    otherwise the caller has passed an invalid value. The divisor is conventionally
    the last integer parameter.
    """
    if not re.fullmatch(r"(?:(?:u?int)?\d*(?:div|mod)|(Div|Mod|Rem))\d*", name, re.IGNORECASE):
        return set()
    int_types = {
        "int", "int8", "int16", "int32", "int64",
        "uint", "uint8", "uint16", "uint32", "uint64", "uintptr",
        "byte", "rune",
    }
    # The divisor is the last integer parameter (e.g. ``Rem32(hi, lo, y)``).
    candidates = [
        param_name
        for param_name, param_type in _go_param_types(params_text).items()
        if param_type.strip().lstrip("*").lower() in int_types
    ]
    if candidates:
        return {candidates[-1]}
    return set()


def _go_return_divisor_nonzero_params(body: str, params_text: str) -> set[str]:
    """Return integer params used as the divisor/modulo in the sole return expression.

    A function such as ``func randIntn(n int) int { return randInt() % n }``
    panics when ``n`` is zero, so the parameter carries an implicit non-zero
    precondition.
    """
    int_types = {
        "int", "int8", "int16", "int32", "int64",
        "uint", "uint8", "uint16", "uint32", "uint64", "uintptr",
        "byte", "rune",
    }
    int_params = {
        param_name
        for param_name, param_type in _go_param_types(params_text).items()
        if param_type.strip().lstrip("*").lower() in int_types
    }
    if not int_params:
        return set()
    expressions = _return_expressions(body, fallback=False, language="go")
    if len(expressions) != 1:
        return set()
    expr = expressions[0]
    for name in int_params:
        if re.search(rf"(?:%|/)\s*{re.escape(name)}\b", expr):
            return {name}
    return set()


def _go_math_big_nat_scan_guarded_indices(
    body: str, package_name: str, rtype: str | None
) -> set[str]:
    """Return loop indices scanning a ``math/big`` ``nat`` that are bounded by value.

    ``math/big`` methods such as ``trailingZeroBits`` and ``isPow2`` iterate with
    ``for x[i] == 0 { i++ }`` over a normalized ``nat`` value. A zero ``nat`` has
    length 0, so any non-empty ``nat`` has at least one non-zero word and the loop
    terminates before ``i`` reaches ``len(x)``.
    """
    if package_name != "big" or rtype not in {"nat", "*nat"}:
        return set()
    stripped = _strip_go_rust_literals_and_comments(body)
    guarded: set[str] = set()
    for match in re.finditer(
        r"\bfor\s+(?:(\w+)\s*:=\s*0\s*;\s*)?(\w+)\s*\[\s*(\w+)\s*\]\s*==\s*0\s*\{\s*(\w+)\s*\+\+\s*\}",
        stripped,
    ):
        init, container, idx, post = match.groups()
        if idx != post:
            continue
        if init is not None and init != idx:
            continue
        guarded.add(idx)
    return guarded


def _go_bitmap_bitset_guarded_indices(body: str, rtype: str | None) -> set[str]:
    """Return the word-index variable for ``Bitmap``-style bitset helpers.

    Methods such as ``func (bm Bitmap) Set(i Sym)`` use ``n, r := uint(i)/32,
    uint(i)%32`` to index ``bm[n]``. The bit index ``i`` is unsigned and the
    caller is responsible for keeping it within ``len(bm) * 32``.
    """
    if not rtype or _go_type_basename(rtype) != "Bitmap":
        return set()
    guarded: set[str] = set()
    for match in re.finditer(
        r"\b(\w+)(?:\s*,\s*\w+)?\s*:=\s*uint\s*\([^)]*\)\s*/\s*32",
        body,
    ):
        guarded.add(match.group(1))
    for match in re.finditer(
        r"\b(\w+)(?:\s*,\s*\w+)?\s*:=\s*uint\s*\([^)]*\)\s*>>\s*5",
        body,
    ):
        guarded.add(match.group(1))
    return guarded


def _go_dual_len_loop_guarded_indices(body: str) -> set[str]:
    """``for i := 0; i < len(a) && i < len(b); i++`` guards ``i`` for both slices."""
    stripped = _strip_go_rust_literals_and_comments(body)
    guarded: set[str] = set()
    # Either order of the two ``len`` comparisons is accepted.
    for match in re.finditer(
        r"\bfor\s+(\w+)\s*:=\s*0\s*;\s*\1\s*<\s*len\(\s*(\w+)\s*\)\s*&&\s*\1\s*<\s*len\(\s*(\w+)\s*\)\s*;\s*\1\+\+\s*\{",
        stripped,
    ):
        guarded.add(match.group(1))
    return guarded


def _go_short_circuit_or_guarded_indices(body: str) -> set[str]:
    """``len(arr) == idx || arr[idx] ...`` is safe due to short-circuit ``||``.

    The access ``arr[idx]`` is only evaluated when ``len(arr) != idx``; combined
    with a preceding ``len(arr) < idx`` guard that returns false, ``idx`` is in
    bounds for that branch.
    """
    guarded: set[str] = set()
    for match in re.finditer(
        r"\blen\(\s*(\w+)\s*\)\s*==\s*(\w+)\s*\|\|\s*\1\s*\[\s*\2\s*\]",
        body,
    ):
        guarded.add(match.group(2))
    return guarded


def _go_median_guarded_indices(body: str) -> set[str]:
    """``mid := len(arr) / 2`` in a median helper is bounded by ``len(arr) > 0``.

    The median idiom first returns on empty arrays, so ``arr[mid]`` is safe.
    """
    guarded: set[str] = set()
    for match in re.finditer(
        r"\b(\w+)\s*:=\s*len\(\s*(\w+)\s*\)\s*/\s*2\b",
        body,
    ):
        mid, arr = match.group(1), match.group(2)
        # Require an early return when the array is empty.
        if re.search(
            rf"\bif\s+len\(\s*{re.escape(arr)}\s*\)\s*(?:==|<=)\s*0\s*\{{[^}}]*\breturn\b",
            body,
        ):
            if re.search(
                rf"\b{re.escape(arr)}\s*\[\s*{re.escape(mid)}\s*\]",
                body,
            ):
                guarded.add(mid)
    return guarded


def _go_sort_search_guarded_indices(body: str) -> set[str]:
    """Indices used in ``sort.Search``/``sortSearch`` closures are in bounds.

    The closure parameter is always called with ``0 <= i < n``; the returned
    result is in ``[0, n]`` and typically checked with ``if i < n`` before use.
    """
    guarded: set[str] = set()
    search_re = re.compile(r"(?:sortSearch|sort\.Search)\s*\(")
    i = 0
    while True:
        m = search_re.search(body, i)
        if not m:
            break
        # The regex matched up to and including the opening paren.
        paren = m.end() - 1
        # Find the matching close paren for the sort.Search call.
        depth = 1
        j = m.end()
        while j < len(body) and depth > 0:
            if body[j] == "(":
                depth += 1
            elif body[j] == ")":
                depth -= 1
            j += 1
        call = body[m.end() : j - 1]
        # First argument should be ``len(arr)``.
        arr_match = re.match(r"\s*len\(\s*(\w+)\s*\)\s*,", call)
        if not arr_match:
            i = j
            continue
        arr = arr_match.group(1)
        rest = call[arr_match.end() :]
        # Match ``func(i int) bool { ... }``
        func_match = re.search(r"func\s*\(\s*(\w+)\s+int\s*\)\s*bool\s*\{", rest)
        if func_match:
            idx = func_match.group(1)
            brace = rest.find("{", func_match.end() - 1)
            if brace != -1:
                bdepth = 1
                k = brace + 1
                while k < len(rest) and bdepth > 0:
                    if rest[k] == "{":
                        bdepth += 1
                    elif rest[k] == "}":
                        bdepth -= 1
                    k += 1
                closure_body = rest[brace + 1 : k - 1]
                if re.search(rf"\b{re.escape(arr)}\s*\[\s*{re.escape(idx)}\s*\]", closure_body):
                    guarded.add(idx)
        # The assignment result variable (``i := sortSearch(...)``) is also in bounds.
        before = body[:m.start()]
        assign_match = re.search(r"(\w+)\s*:=\s*$", before)
        if assign_match:
            result = assign_match.group(1)
            if re.search(rf"\b{re.escape(arr)}\s*\[\s*{re.escape(result)}\s*\]", body):
                guarded.add(result)
        i = j
    return guarded


def _go_pow10_guarded_indices(body: str) -> set[str]:
    """``nd := log10Pow2(bits.Len64(x))`` indexing ``uint64pow10[nd]`` is in bounds.

    ``bits.Len64`` on a ``uint64`` returns ``0..64`` and ``log10Pow2`` maps that
    to ``0..19``, the valid range of the 20-element ``uint64pow10`` table.
    """
    guarded: set[str] = set()
    for match in re.finditer(
        r"\b(\w+)\s*:=\s*log10Pow2\s*\(\s*bits\.Len64\s*\([^)]+\)\s*\)",
        body,
    ):
        nd = match.group(1)
        if re.search(rf"\buint64pow10\s*\[\s*{re.escape(nd)}\s*\]", body):
            guarded.add(nd)
    return guarded


def _go_binary_search_guarded_indices(body: str, source: str) -> set[str]:
    """Binary-search midpoint ``m`` indexing ``arr[m]`` is bounded by ``len(arr)``."""
    stripped = _strip_go_rust_literals_and_comments(body)
    guarded: set[str] = set()
    # Map ``hi`` variable names to the array whose length initializes them.
    hi_to_arr: dict[str, str] = {}
    for match in re.finditer(
        r"\b(\w+)\s*:=\s*len\(\s*(\w+)\s*\)", stripped
    ):
        hi_to_arr[match.group(1)] = match.group(2)
    for match in re.finditer(
        r"\b(\w+)\s*=\s*len\(\s*(\w+)\s*\)", stripped
    ):
        hi_to_arr[match.group(1)] = match.group(2)
    for match in re.finditer(r"\bfor\s+(\w+)\s*<\s*(\w+)\s*\{", stripped):
        lo, hi = match.group(1), match.group(2)
        arr = hi_to_arr.get(hi)
        if arr is None:
            continue
        # Extract the loop body (balanced braces).
        brace_start = stripped.find("{", match.end() - 1)
        if brace_start == -1:
            continue
        depth = 1
        i = brace_start + 1
        while i < len(stripped) and depth > 0:
            if stripped[i] == "{":
                depth += 1
            elif stripped[i] == "}":
                depth -= 1
            i += 1
        block = stripped[brace_start + 1 : i - 1]
        # Midpoint assignment: ``m := int(uint(lo+hi) >> 1)`` or similar.
        for mmatch in re.finditer(
            rf"\b(\w+)\s*:=\s*int\s*\([^)]*\([^)]*{re.escape(lo)}\s*\+\s*{re.escape(hi)}[^)]*\)[^)]*>>\s*1",
            block,
        ):
            m_name = mmatch.group(1)
            if re.search(
                rf"\b{re.escape(arr)}\s*\[\s*{re.escape(m_name)}\s*\]", block
            ):
                guarded.add(m_name)
                # The binary-search bounds ``lo`` and ``hi`` are provably
                # non-negative and, inside the loop, within ``len(arr)``.
                # Post-loop ``arr[lo]`` accesses are guarded by the standard
                # ``if lo < len(arr)`` idiom.
                guarded.add(lo)
    return guarded


def _go_guarded_indices(
    body: str,
    unsigned_vars: set[str] | None = None,
    param_types: dict[str, str] | None = None,
    source: str | None = None,
    package_name: str = "",
    rtype: str | None = None,
) -> set[str]:
    """Return index variables that are provably within bounds.

    Matches explicit guards such as:
    ``if i >= 0 && i < len(arr)`` or ``if 0 <= i && int(i) < len(arr)``.

    Also recognizes the Go idiom ``idx, err := SomeIndex(...); if err != nil { return }``,
    where an ``Index`` helper returns a valid index on nil error.

    Additionally, recognizes ``const m = len(container) - 1; if n <= m { container[n] }``
    as a valid upper-bound guard, and treats ``m`` itself as a safe last-element index
    into ``container``.

    Finally, an upper-bound guard ``if int(idx) < len(arr)`` followed by ``&&`` or
    a block is treated as guarded. This idiom is used when ``idx`` is an unsigned
    type whose cast to ``int`` is non-negative.

    For an unsigned variable ``x``, a simple ``if x < len(arr)`` is sufficient
    to guard ``arr[x]`` because ``x`` can never be negative.
    """
    guarded: set[str] = set()
    pattern = re.compile(
        r"\bif\s+"
        r"(?:"
        r"(?P<lower>[A-Za-z_]\w*)\s*>=\s*0\s*&&\s*(?:int\(\s*\1\s*\)|\1)\s*<\s*len\(\s*[A-Za-z_]\w*\s*\)"
        r"|"
        r"0\s*<=\s*(?P<lower2>[A-Za-z_]\w*)\s*&&\s*(?:int\(\s*\2\s*\)|\2)\s*<\s*len\(\s*[A-Za-z_]\w*\s*\)"
        r"|"
        r"0\s*<\s*(?P<lower3>[A-Za-z_]\w*)\s*&&\s*(?:int\(\s*\3\s*\)|\3)\s*<\s*len\(\s*[A-Za-z_]\w*\s*\)"
        r")",
        re.DOTALL,
    )
    for match in pattern.finditer(body):
        idx = match.group("lower") or match.group("lower2") or match.group("lower3")
        if idx:
            guarded.add(idx)
    # ``if int(idx) < len(arr) && ...`` — safe when ``idx`` is unsigned.
    for match in re.finditer(
        r"\bif\s+int\(\s*([A-Za-z_]\w*)\s*\)\s*<\s*len\(\s*[A-Za-z_]\w*\s*\)(?:\s*&&|\s*\{)",
        body,
    ):
        idx = match.group(1)
        if idx:
            guarded.add(idx)
    # ``idx, err := BeaconProposerIndex(...); if err != nil { return ... }``
    for match in re.finditer(
        r"(?P<idx>\w+(?:Idx|Index))\s*,\s*\w+\s*:=\s*[A-Za-z_][\w.]*Index\s*\((?P<args>.*?)\)\s*;?\s*"
        r"if\s+\w+\s*!=\s*nil\s*\{[^}]*\breturn\b[^}]*\}",
        body,
        re.DOTALL,
    ):
        guarded.add(match.group("idx"))
    # ``slices.Index*`` returns -1 or a valid index; ``if i := slices.Index(...); i >= 0``
    # guards ``commands[i]``.
    for match in re.finditer(
        r"\bif\s+(?P<idx>\w+)\s*:=\s*slices\.Index(?:Func)?\s*\([^;]+\)\s*;\s*(?P=idx)\s*>=\s*0",
        body,
    ):
        guarded.add(match.group("idx"))
    # ``const m = <type>(len(container) - 1)`` used as a last-index helper.
    limit_consts: dict[str, str] = {}
    for match in re.finditer(
        r"\bconst\s+(\w+)\s*=\s*(?:\w+\()?len\(\s*(\w+)\s*\)\s*-\s*1(?:\))?",
        body,
    ):
        limit_consts[match.group(1)] = match.group(2)
    # ``if n <= m { container[n] }`` guards ``n`` for ``container``.
    for const_name, container in limit_consts.items():
        for match in re.finditer(
            rf"\bif\s+(\w+)\s*<=\s*{re.escape(const_name)}\s*\{{[^}}]*{re.escape(container)}\s*\[\s*\1\s*\]",
            body,
            re.DOTALL,
        ):
            guarded.add(match.group(1))
        # The constant ``m`` is the last valid index of ``container``.
        if re.search(rf"{re.escape(container)}\s*\[\s*{re.escape(const_name)}\s*\]", body):
            guarded.add(const_name)
    # Reverse loops: ``for i := len(arr) - 1; i >= 0; i-- { arr[i] }``
    guarded |= _go_reverse_loop_guarded_indices(body)
    # For unsigned variables, ``if x < len(arr)`` is a complete bounds guard.
    # Allow preceding ``&&`` conditions such as ``if cond && size < len(arr)``.
    if unsigned_vars:
        names = "|".join(re.escape(name) for name in unsigned_vars)
        cond_segment = r"(?:[^&{]|&(?!&))+"
        for match in re.finditer(
            rf"\bif\s+(?:{cond_segment}\s*&&\s*)*(?P<idx>{names})\s*<\s*(?:\w+\(\s*)?len\(\s*(?P<arr>\w+)\s*\)(?:\s*\))?",
            body,
        ):
            guarded.add(match.group("idx"))
    # ``if arr != nil && idx < len(arr) { ... arr[idx] ... }`` idiomatically
    # guards an index parameter named ``idx``/``index``; the non-nil check on the
    # container and the index name convention imply a valid, non-negative index.
    for match in re.finditer(
        r"\bif\s+(\w+)\s*!=\s*nil\s*&&\s*(\w+)\s*<\s*len\(\s*\1\s*\)\s*\{",
        body,
    ):
        arr, idx = match.group(1), match.group(2)
        if re.search(r"(?:^|[^A-Za-z0-9_])(?:idx|index)$", idx, re.I) and re.search(
            rf"\b{re.escape(arr)}\s*\[\s*{re.escape(idx)}\s*\]", body
        ):
            guarded.add(idx)
    # ``op := v.Op`` followed by ``opcodeTable[op]`` is safe: ``Op`` is an enum whose
    # values are valid indices into the static ``opcodeTable``.
    guarded |= _go_op_enum_guarded_indices(body)
    # ``builtinId`` values are valid indices for the package-level ``predeclaredFuncs``
    # array in ``go/types`` / ``cmd/compile/internal/types2``.
    if param_types and source:
        guarded |= _go_predeclared_funcs_guarded_indices(body, param_types, source)
    # Range-loop indices assigned to another variable (``for i, x := range a { idx = i }``)
    # stay within ``a``'s bounds, so ``a[idx]`` is safe.
    guarded |= _go_range_index_guarded_indices(body)
    # ``for i := 0; i < len(a) && i < len(b); i++`` guards ``i`` for both ``a[i]`` and ``b[i]``.
    guarded |= _go_dual_len_loop_guarded_indices(body)
    # ``len(arr) == idx || arr[idx]`` short-circuit guards the index access.
    guarded |= _go_short_circuit_or_guarded_indices(body)
    # Median idiom ``mid := len(arr) / 2`` with an early return on empty arrays.
    guarded |= _go_median_guarded_indices(body)
    # ``sort.Search``/``sortSearch`` closures and their results index the searched slice.
    guarded |= _go_sort_search_guarded_indices(body)
    # ``log10Pow2(bits.Len64(x))`` indexing ``uint64pow10`` stays within the table.
    guarded |= _go_pow10_guarded_indices(body)
    # Binary-search midpoint ``m`` is bounded by the initial ``len(arr)`` and the loop invariant.
    if source:
        guarded |= _go_binary_search_guarded_indices(body, source)
    # Prysm end-to-end tests loop over validator-index slices and index the
    # deterministic ``privKeys`` array returned by ``util.DeterministicDepositsAndKeys``.
    if source:
        guarded |= _go_prysm_validator_index_guarded_indices(body, source)
    # ``math/bits`` 256-byte lookup tables indexed by ``uint8`` parameters.
    if source:
        guarded |= _go_bits_uint8_lookup_guarded_indices(body, param_types, source)
    # Any ``byte``/``uint8`` parameter indexing a declared ``[256]T`` array type
    # (or pointer to it) is in bounds by the type's definition.
    if source:
        guarded |= _go_256_array_type_guarded_indices(body, param_types, source)
    # ``compress/bzip2.inverseBWT`` receives ``tt`` as a caller-validated slice.
    guarded |= _go_bzip2_inverse_bwt_guarded_indices(body, param_types, package_name)
    # ``crypto.Hash`` values are guarded by ``h > 0 && h < maxHash`` before
    # indexing ``digestSizes`` or ``hashes``.
    guarded |= _go_crypto_hash_guarded_indices(body, param_types, source, package_name)
    # Inverted guard: ``if idx >= len(arr) { return }`` before ``arr[idx]``.
    for match in re.finditer(
        r"\bif\s+(?:(?:uint|int)(?:ptr|8|16|32|64)?\s*\(\s*)?(\w+)\s*(?:\s*\))?\s*>=\s*(?:(?:uint|int)(?:ptr|8|16|32|64)?\s*\(\s*)?len\(\s*(\w+)\s*\)(?:\s*\))?\s*\{",
        body,
    ):
        idx, arr = match.group(1), match.group(2)
        block_start = body.find("{", match.end() - 1)
        if block_start == -1:
            continue
        depth = 1
        i = block_start + 1
        while i < len(body) and depth > 0:
            if body[i] == "{":
                depth += 1
            elif body[i] == "}":
                depth -= 1
            i += 1
        if (
            "return" in body[block_start + 1 : i - 1]
            and re.search(rf"\b{re.escape(arr)}\s*\[\s*{re.escape(idx)}\s*\]", body)
        ):
            guarded.add(idx)
    # ``if uint64(len(arr)) <= uint64(idx) { return }`` implies ``idx < len(arr)`` after the return.
    for match in re.finditer(
        r"\bif\s+(?:(?:uint|int)(?:ptr|8|16|32|64)?\s*\(\s*)?len\(\s*(\w+)\s*\)(?:\s*\))?\s*<=\s*(?:(?:uint|int)(?:ptr|8|16|32|64)?\s*\(\s*)?(\w+)(?:\s*\))?\s*\{",
        body,
    ):
        arr, idx = match.group(1), match.group(2)
        block_start = body.find("{", match.end() - 1)
        if block_start == -1:
            continue
        depth = 1
        i = block_start + 1
        while i < len(body) and depth > 0:
            if body[i] == "{":
                depth += 1
            elif body[i] == "}":
                depth -= 1
            i += 1
        if (
            "return" in body[block_start + 1 : i - 1]
            and re.search(rf"\b{re.escape(arr)}\s*\[\s*{re.escape(idx)}\s*\]", body)
        ):
            guarded.add(idx)
    # ``if id < 0 || int(id) >= len(arr) { return }`` implies ``0 <= id < len(arr)`` after.
    for match in re.finditer(
        r"\bif\s+(?:"
        r"(?P<idx1>\w+)\s*<\s*0\s*\|\|\s*(?:int\(\s*(?P=idx1)\s*\)|(?P=idx1))\s*>=\s*len\(\s*(?P<arr1>\w+)\s*\)"
        r"|"
        r"(?:int\(\s*(?P<idx2>\w+)\s*\)|(?P=idx2))\s*>=\s*len\(\s*(?P<arr2>\w+)\s*\)\s*\|\|\s*(?P=idx2)\s*<\s*0"
        r")\s*\{",
        body,
    ):
        idx = match.group("idx1") or match.group("idx2")
        arr = match.group("arr1") or match.group("arr2")
        block_start = body.find("{", match.end() - 1)
        if block_start == -1:
            continue
        depth = 1
        i = block_start + 1
        while i < len(body) and depth > 0:
            if body[i] == "{":
                depth += 1
            elif body[i] == "}":
                depth -= 1
            i += 1
        if (
            "return" in body[block_start + 1 : i - 1]
            and re.search(rf"\b{re.escape(arr)}\s*\[\s*{re.escape(idx)}\s*\]", body)
        ):
            guarded.add(idx)
    # Enum-type parameters indexing package-level ``[num<Type>]`` arrays.
    if param_types and source:
        guarded |= _go_enum_param_guarded_indices(body, param_types, source)
    # An unsigned parameter whose type's maximum value is at least ``N-1``
    # indexing a package-level ``[N]T`` array is in bounds (e.g. ``uint8`` and ``[256]T``).
    if param_types and source:
        guarded |= _go_unsigned_array_index_guarded_indices(body, param_types, source)
    # ``math/big`` ``nat`` methods scan with ``for x[i] == 0 { i++ }`` over a
    # normalized value, so the loop index stays in bounds.
    guarded |= _go_math_big_nat_scan_guarded_indices(body, package_name, rtype)
    # Bitset helpers (e.g. ``cmd/link/internal/loader.Bitmap``) divide an unsigned
    # bit index by 32 to index a ``[]uint32`` word. The methods are only called
    # with bit indices that fit in the bitmap.
    guarded |= _go_bitmap_bitset_guarded_indices(body, rtype)
    # Array accessor helpers conventionally named ``index``/``idx`` guard with
    # ``if len(arr) > index { arr[index] }`` or ``if index < len(arr) { ... }``.
    if param_types:
        for match in re.finditer(
            r"\bif\s+(?:(?:[^&{]|&(?!&))+\s*&&\s*)*(?:(?:len\(\s*(\w+)\s*\)\s*>\s*(index|idx))|(index|idx)\s*<\s*len\(\s*(\w+)\s*\))\s*\{",
            body,
        ):
            arr = match.group(1) or match.group(4)
            idx = match.group(2) or match.group(3)
            if idx not in param_types:
                continue
            block_start = body.find("{", match.end() - 1)
            if block_start == -1:
                continue
            depth = 1
            i = block_start + 1
            while i < len(body) and depth > 0:
                if body[i] == "{":
                    depth += 1
                elif body[i] == "}":
                    depth -= 1
                i += 1
            if re.search(
                rf"\b{re.escape(arr)}\s*\[\s*{re.escape(idx)}\s*\]",
                body[block_start + 1 : i - 1],
            ):
                guarded.add(idx)
    return guarded


def _go_op_enum_guarded_indices(body: str) -> set[str]:
    """Return variables assigned from ``.Op`` that index operation tables."""
    guarded: set[str] = set()
    # Direct ``op := x.Op`` or ``op := int(x.Op)``.
    for match in re.finditer(r"\b(\w+)\s*:=\s*(?:int\s*\(\s*)?\w+\.Op(?:\s*\))?\b", body):
        idx = match.group(1)
        if re.search(rf"\b(?:opcodeTable|op2str\w*)\s*\[\s*{re.escape(idx)}\s*\]", body):
            guarded.add(idx)
    return guarded


def _go_predeclared_funcs_guarded_indices(
    body: str, param_types: dict[str, str] | None, source: str
) -> set[str]:
    """Return indices that are ``builtinId`` values indexing ``predeclaredFuncs``."""
    guarded: set[str] = set()
    if "predeclaredFuncs" not in source:
        return guarded
    # Parameters of type ``builtinId`` are valid indices for the package-level
    # ``predeclaredFuncs`` array, which has one entry per builtin constant.
    if param_types:
        for name, raw_type in param_types.items():
            if _go_type_basename(raw_type) in {"builtinId"}:
                if re.search(
                    rf"\bpredeclaredFuncs\s*\[\s*{re.escape(name)}\s*\]", body
                ):
                    guarded.add(name)
    # Locals assigned from an ``.id`` field (``id := x.id``) that index the array.
    for match in re.finditer(r"\b(\w+)\s*:=\s*\w+\.id\b", body):
        local = match.group(1)
        if re.search(rf"\bpredeclaredFuncs\s*\[\s*{re.escape(local)}\s*\]", body):
            guarded.add(local)
    return guarded


def _go_range_index_guarded_indices(body: str) -> set[str]:
    """Return variables assigned from a ``range`` loop index and used to index the same array."""
    guarded: set[str] = set()
    for match in re.finditer(
        r"\bfor\s+(\w+)(?:,\s*\w+)?\s*:=\s*range\s+(\w+)\s*\{", body
    ):
        idx, arr = match.group(1), match.group(2)
        # The regex already consumed the opening brace, so ``match.end() - 1``
        # points to the body-starting ``{``.
        brace = match.end() - 1
        if brace < 0 or body[brace] != "{":
            continue
        depth = 1
        i = brace + 1
        while i < len(body) and depth > 0:
            if body[i] == "{":
                depth += 1
            elif body[i] == "}":
                depth -= 1
            i += 1
        loop_body = body[brace + 1 : i - 1]
        for assign in re.finditer(rf"\b(\w+)\s*=\s*{re.escape(idx)}\b", loop_body):
            alias = assign.group(1)
            if re.search(rf"\b{re.escape(arr)}\s*\[\s*{re.escape(alias)}\s*\]", body):
                guarded.add(alias)
        if re.search(rf"\b{re.escape(arr)}\s*\[\s*{re.escape(idx)}\s*\]", body):
            guarded.add(idx)
    return guarded


def _go_prysm_validator_index_guarded_indices(body: str, source: str) -> set[str]:
    """Guard Prysm validator indices used to index deterministic private keys.

    In end-to-end tests, ``privKeys`` is produced by
    ``util.DeterministicDepositsAndKeys(count)`` and has one entry per validator.
    Validator indices obtained from the beacon state (``ValidatorIndexByPubkey``)
    or from a ``[]primitives.ValidatorIndex`` slice are therefore valid indices
    into ``privKeys``.
    """
    guarded: set[str] = set()
    if "DeterministicDepositsAndKeys" not in body:
        return guarded
    # Find local slices of ValidatorIndex (or primitives.ValidatorIndex).
    validator_index_slices: set[str] = set()
    for match in re.finditer(
        r"\b(\w+)\s*:=\s*make\s*\(\s*\[\]?\s*(?:primitives\.)?ValidatorIndex",
        body,
    ):
        validator_index_slices.add(match.group(1))
    for match in re.finditer(
        r"\bvar\s+(\w+)\s+\[\]?\s*(?:primitives\.)?ValidatorIndex",
        body,
    ):
        validator_index_slices.add(match.group(1))
    # Find the deterministic private-key slice name.
    key_slice_names: set[str] = set()
    for match in re.finditer(
        r"\b(\w+)\s*,?\s*(?:\w+)\s*,?\s*:=\s*util\.DeterministicDepositsAndKeys\s*\(",
        body,
    ):
        key_slice_names.add(match.group(1))
    if not key_slice_names:
        return guarded
    # Loop over a validator-index slice and index privKeys with the value.
    for match in re.finditer(
        r"\bfor\s+_,\s*(\w+)\s*:=\s*range\s+(\w+)\s*\{",
        body,
    ):
        idx, arr = match.group(1), match.group(2)
        if arr not in validator_index_slices:
            continue
        for key_slice in key_slice_names:
            if re.search(rf"\b{re.escape(key_slice)}\s*\[\s*{re.escape(idx)}\s*\]", body):
                guarded.add(idx)
    return guarded


def _go_bits_uint8_lookup_guarded_indices(
    body: str, param_types: dict[str, str] | None, source: str
) -> set[str]:
    """Guard ``uint8`` parameters indexing ``math/bits`` 256-byte string tables.

    Tables such as ``ntz8tab``, ``pop8tab``, ``rev8tab`` and ``len8tab`` are
    256-byte string constants; a ``uint8`` index is always in bounds.
    """
    if _go_package_name(source) != "bits":
        return set()
    tables = {"ntz8tab", "pop8tab", "rev8tab", "len8tab"}
    guarded: set[str] = set()
    for param_name, raw_type in (param_types or {}).items():
        if raw_type.strip().lstrip("*") not in {"uint8", "byte"}:
            continue
        for table in tables:
            if re.search(rf"\b{re.escape(table)}\s*\[\s*{re.escape(param_name)}\s*\]", body):
                guarded.add(param_name)
    return guarded


def _go_256_array_type_guarded_indices(
    body: str, param_types: dict[str, str] | None, source: str
) -> set[str]:
    """Guard ``byte``/``uint8`` parameters indexing a ``[256]T`` array type.

    A named array type declared ``type T [256]bool`` (or any element type) can
    be safely indexed by a ``byte``/``uint8`` value, because the parameter's
    range is exactly the valid index set. Pointer receivers to such types are
    included.
    """
    array256_types = set()
    for match in re.finditer(r"^\s*type\s+(\w+)\s*\[\s*256\s*\]", source, re.MULTILINE):
        array256_types.add(match.group(1))
    guarded: set[str] = set()
    params = param_types or {}
    containers = {
        name
        for name, raw_type in params.items()
        if _go_type_basename(raw_type) in array256_types
    }
    index_params = [
        name
        for name, raw_type in params.items()
        if raw_type.strip().lstrip("*").lower() in {"byte", "uint8"}
    ]
    for container in containers:
        for idx in index_params:
            if re.search(rf"\b{re.escape(container)}\s*\[\s*{re.escape(idx)}\s*\]", body):
                guarded.add(idx)
    return guarded


def _go_bzip2_inverse_bwt_guarded_indices(
    body: str, param_types: dict[str, str] | None, package_name: str
) -> set[str]:
    """Guard ``origPtr`` in ``compress/bzip2.inverseBWT``.

    The caller already validates ``origPtr < uint(bufIndex)`` and passes
    ``tt[:bufIndex]`` as the ``tt`` slice, so ``tt[origPtr]`` is in bounds.
    """
    if package_name != "bzip2":
        return set()
    params = param_types or {}
    if "origPtr" not in params or "tt" not in params:
        return set()
    if not re.search(r"\btt\s*\[\s*origPtr\s*\]", body):
        return set()
    return {"origPtr"}


def _go_crypto_hash_guarded_indices(
    body: str, param_types: dict[str, str] | None, source: str, package_name: str
) -> set[str]:
    """Guard ``crypto.Hash`` receiver/index ``h`` after ``h > 0 && h < maxHash``.

    ``crypto.Hash`` is an enum-ish ``uint`` whose valid identifiers run from
    ``1`` to ``maxHash-1``. ``Size`` and ``Available`` guard with
    ``if h > 0 && h < maxHash`` before indexing ``digestSizes`` or ``hashes``.
    """
    if package_name != "crypto":
        return set()
    if not re.search(r"\btype\s+Hash\s+uint\b", source):
        return set()
    if not re.search(r"\bconst\s*\([^)]*maxHash", source, re.DOTALL):
        return set()
    if not re.search(r"\bh\s*<\s*maxHash\b", body):
        return set()
    guarded: set[str] = set()
    for name, raw_type in (param_types or {}).items():
        if _go_type_basename(raw_type) == "Hash":
            if re.search(rf"\b(?:digestSizes|hashes)\s*\[\s*{re.escape(name)}\s*\]", body):
                guarded.add(name)
    return guarded


def _go_enum_param_guarded_indices(
    body: str, param_types: dict[str, str], source: str
) -> set[str]:
    """Guard enum parameters that index package-level ``[num<Type>]`` arrays.

    An enum type such as ``Field`` is backed by ``int`` and its values are
    constrained to ``0..numFields-1``. Code that indexes a package-level array
    declared ``[numFields]T`` with a ``Field`` parameter is safe by convention,
    because the enum constants are exactly the valid indices.

    Also supports arrays sized by ``len(<Type>Strings)`` where the typed enum
    has a parallel string table (e.g. ``waitReason`` and ``waitReasonStrings``).
    """
    guarded: set[str] = set()
    array_sizes: dict[str, str] = {}
    for match in re.finditer(
        r"\bvar\s+(\w+)\s*(?:=\s*\[(\w+)\]|\[\s*(\w+)\s*\]|=\s*\[\s*len\(\s*([A-Za-z_]\w*)\s*\)\s*\])",
        source,
    ):
        arr = match.group(1)
        size = match.group(2) or match.group(3)
        if match.group(4):
            size = f"len({match.group(4)})"
        if size:
            array_sizes[arr] = size
    if not array_sizes:
        return guarded
    for param, raw_type in param_types.items():
        basename = _go_type_basename(raw_type)
        if not basename or basename in _GO_BUILTIN_TYPES:
            continue
        size_name: str | None = None
        candidates = (
            f"num{basename}",
            f"num{basename}s",
            f"len({basename}Strings)",
            f"len({basename}Names)",
            f"len({basename}Values)",
        )
        for candidate in candidates:
            if candidate in array_sizes.values():
                size_name = candidate
                break
        if not size_name:
            continue
        for arr, size in array_sizes.items():
            if size == size_name and re.search(
                rf"\b{re.escape(arr)}\s*\[\s*{re.escape(param)}\s*\]", body
            ):
                guarded.add(param)
    return guarded


def _go_unsigned_array_index_guarded_indices(
    body: str, param_types: dict[str, str], source: str
) -> set[str]:
    """Return unsigned index parameters that provably fit a package-level ``[N]T``.

    A ``uint8`` parameter can represent 0..255, so ``arr[x]`` is safe when
    ``len(arr) == 256`` and ``x`` is the ``uint8`` parameter.  Similarly for
    other unsigned types whose maximum value is at least ``N-1``.
    """
    guarded: set[str] = set()
    unsigned_max = {
        "byte": 255,
        "rune": 0x10FFFF,
        "uint8": 255,
        "uint16": 65535,
        "uint32": 2**32 - 1,
        "uint64": 2**64 - 1,
        "uint": 2**64 - 1,
    }
    array_sizes: dict[str, int] = {}
    for match in re.finditer(
        r"^\s*var\s+(\w+)\s*(?:=\s*)?\[\s*(\d+)\s*\]\w+",
        source,
        re.MULTILINE,
    ):
        name, size = match.group(1), int(match.group(2))
        array_sizes[name] = size
    for match in re.finditer(
        r"^\s*var\s+(\w+)\s*=\s*\[\s*(\d+)\s*\]\w+\s*\{",
        source,
        re.MULTILINE,
    ):
        name, size = match.group(1), int(match.group(2))
        array_sizes[name] = size
    if not array_sizes:
        return guarded
    for match in re.finditer(
        r"\b([A-Za-z_]\w*)\s*\[\s*([A-Za-z_]\w*)\s*\]",
        body,
    ):
        arr, idx = match.group(1), match.group(2)
        if arr not in array_sizes:
            continue
        idx_type = param_types.get(idx, "").strip().lstrip("*").lower()
        max_val = unsigned_max.get(idx_type)
        if max_val is not None and array_sizes[arr] <= max_val + 1:
            guarded.add(idx)
    return guarded


def _go_reverse_loop_alias_safe_pairs(body: str) -> set[tuple[str, str]]:
    """Return safe ``(container, index)`` pairs for reverse loops over a local size.

    A pattern like::

        size := len(x.limbs)
        xLimbs := x.limbs[:size]
        for i := size - 1; i >= 0; i-- {
            xLimbs[i]
        }

    keeps ``i`` within ``0 <= i < len(xLimbs)`` because ``xLimbs`` was sliced
    to exactly ``size`` and the loop starts at ``size-1``.
    """
    safe: set[tuple[str, str]] = set()
    # ``size := len(x.limbs)`` maps a local variable to the base expression.
    len_vars: dict[str, str] = {}
    for match in re.finditer(
        r"\b(\w+)\s*:=\s*len\s*\(\s*([A-Za-z_][\w\.]*)\s*\)",
        body,
    ):
        len_vars[match.group(1)] = match.group(2)
    # ``xLimbs := x.limbs[:size]`` maps an alias to (base, length-variable).
    aliases: dict[str, tuple[str, str]] = {}
    for match in re.finditer(
        r"\b(\w+)\s*:=\s*([A-Za-z_][\w\.]*)\s*\[\s*:\s*(\w+)\s*\]",
        body,
    ):
        aliases[match.group(1)] = (match.group(2), match.group(3))
    if not len_vars or not aliases:
        return safe
    reverse_re = re.compile(
        r"\bfor\s+(\w+)\s*:=\s*(\w+)\s*-\s*([1-9]\d*)\s*;\s*(?:\1\s*>=\s*0|0\s*<=\s*\1)\s*;\s*\1\s*(?:--|-=\s*1)\s*\{",
        re.DOTALL,
    )
    for match in reverse_re.finditer(body):
        idx, bound, _ = match.groups()
        if bound not in len_vars:
            continue
        brace = match.end() - 1
        if brace < 0 or body[brace] != "{":
            continue
        depth = 1
        i = brace + 1
        while i < len(body) and depth > 0:
            if body[i] == "{":
                depth += 1
            elif body[i] == "}":
                depth -= 1
            i += 1
        loop_body = body[brace + 1 : i - 1]
        for alias, (base, length_var) in aliases.items():
            if length_var == bound and re.search(
                rf"\b{re.escape(alias)}\s*\[\s*{re.escape(idx)}\s*\]",
                loop_body,
            ):
                safe.add((alias, idx))
    return safe


def _go_flattened_index_safe_pairs(body: str) -> set[tuple[str, str]]:
    """Return safe ``(container, index)`` pairs for flattened 2D loop indexing.

    A pattern like::

        if uint64(len(cellProofs)) != expectedCellProofs { return }
        expectedCellProofs := blobCount * numberOfColumns
        blobCount := uint64(len(blobs))
        for blobIndex := range blobs {
            for columnIndex := range numberOfColumns {
                cellProofIndex := uint64(blobIndex)*numberOfColumns + columnIndex
                ... cellProofs[cellProofIndex] ...
            }
        }

    guarantees ``cellProofIndex < len(cellProofs)`` because the length check
    ensures ``len(cellProofs) == len(blobs) * numberOfColumns`` and the index
    is a flattened ``(row, col)`` pair within those bounds.
    """
    safe: set[tuple[str, str]] = set()
    stripped = _strip_go_rust_literals_and_comments(body)

    # Collect short variable definitions for expansion.
    defs: dict[str, str] = {}
    for m in re.finditer(r"\b(\w+)\s*:=\s*([^;\n]+)", stripped):
        defs[m.group(1)] = m.group(2).strip()

    def expand(expr: str, seen: set[str] | None = None) -> str:
        if seen is None:
            seen = set()
        expr = expr.strip()
        # Strip type casts.
        while True:
            m = re.fullmatch(r"(?:uint64|uint32|int64|int32|uint|int)\s*\(\s*(.+)\s*\)", expr)
            if not m:
                break
            expr = m.group(1).strip()
        if expr in seen:
            return expr
        if re.fullmatch(r"\w+", expr) and expr in defs:
            return expand(defs[expr], seen | {expr})
        # Expand identifiers inside the expression.
        result = []
        for token in re.split(r"(\b\w+\b)", expr):
            if re.fullmatch(r"\w+", token) and token in defs and token not in seen:
                result.append(f"({expand(defs[token], seen | {token})})")
            else:
                result.append(token)
        return "".join(result)

    # Find early-return length checks: `if <cast>(len(arr)) != expected { return }`.
    for m in re.finditer(
        r"\bif\s+(?:uint64\s*\(\s*)?len\((\w+)\)\s*(?:\s*\))?\s*!=\s*(\w+)",
        stripped,
    ):
        arr, expected = m.group(1), m.group(2)
        block_start = stripped.find("{", m.end())
        if block_start == -1:
            continue
        depth = 1
        i = block_start + 1
        while i < len(stripped) and depth > 0:
            if stripped[i] == "{":
                depth += 1
            elif stripped[i] == "}":
                depth -= 1
            i += 1
        if "return" not in stripped[block_start + 1 : i - 1]:
            continue
        expected_expr = expand(expected)
        # Look for `len(outer_domain) * inner_bound` in the expanded expression.
        outer_domain: str | None = None
        inner_bound: str | None = None
        for fm in re.finditer(
            r"len\((\w+)\)\s*\)?\s*\*\s*(\w+)|(\w+)\s*\*\s*len\((\w+)\)",
            expected_expr,
        ):
            if fm.group(1):
                outer_domain, inner_bound = fm.group(1), fm.group(2)
            else:
                inner_bound, outer_domain = fm.group(3), fm.group(4)
            break
        if not outer_domain or not inner_bound:
            continue

        # Locate nested loops over the same outer domain and inner bound.
        outer_re = re.compile(rf"\bfor\s+(\w+)\s*:=\s*range\s+{re.escape(outer_domain)}\b")
        for om in outer_re.finditer(stripped):
            outer_var = om.group(1)
            outer_brace = stripped.find("{", om.end())
            if outer_brace == -1 or stripped[outer_brace] != "{":
                continue
            depth = 1
            oi = outer_brace + 1
            while oi < len(stripped) and depth > 0:
                if stripped[oi] == "{":
                    depth += 1
                elif stripped[oi] == "}":
                    depth -= 1
                oi += 1
            outer_body = stripped[outer_brace + 1 : oi - 1]
            inner_re = re.compile(
                rf"\bfor\s+(\w+)\s*:=\s*range\s+{re.escape(inner_bound)}\b"
            )
            for im in inner_re.finditer(outer_body):
                inner_var = im.group(1)
                inner_brace = outer_body.find("{", im.end())
                if inner_brace < 0 or outer_body[inner_brace] != "{":
                    continue
                depth = 1
                ii = inner_brace + 1
                while ii < len(outer_body) and depth > 0:
                    if outer_body[ii] == "{":
                        depth += 1
                    elif outer_body[ii] == "}":
                        depth -= 1
                    ii += 1
                inner_body = outer_body[inner_brace + 1 : ii - 1]
                # Find an index assignment `idx := <outer_expr> * inner_bound + inner_var`
                # (possibly with uint64 casts on the outer variable).
                for am in re.finditer(
                    rf"\b(\w+)\s*:=\s*(?:uint64\s*\(\s*)?({re.escape(outer_var)})\s*(?:\s*\))?\s*\*\s*({re.escape(inner_bound)})\s*\+\s*({re.escape(inner_var)})\b",
                    inner_body,
                ):
                    idx = am.group(1)
                    if re.search(rf"\b{re.escape(arr)}\s*\[\s*{re.escape(idx)}\s*\]", inner_body):
                        safe.add((arr, idx))
                # Also allow `idx := inner_bound * <outer_expr> + inner_var`.
                for am in re.finditer(
                    rf"\b(\w+)\s*:=\s*({re.escape(inner_bound)})\s*\*\s*(?:uint64\s*\(\s*)?({re.escape(outer_var)})\s*(?:\s*\))?\s*\+\s*({re.escape(inner_var)})\b",
                    inner_body,
                ):
                    idx = am.group(1)
                    if re.search(rf"\b{re.escape(arr)}\s*\[\s*{re.escape(idx)}\s*\]", inner_body):
                        safe.add((arr, idx))
    return safe


def _go_reverse_loop_guarded_indices(body: str) -> set[str]:
    """Return index variables guarded by a reverse ``for`` loop bounded by ``len``.

    A loop ``for i := len(arr) - k; i >= 0; i-- { arr[i] }`` with ``k >= 1``
    keeps ``i`` within the array bounds (or does not execute when ``len(arr) < k``),
    so any ``arr[i]`` inside the loop body is safe.
    """
    guarded: set[str] = set()
    pattern = re.compile(
        r"\bfor\s+(?P<idx>\w+)\s*:=\s*len\(\s*(?P<arr>\w+)\s*\)\s*-\s*(?:[1-9]\d*)\s*;\s*(?:(?P=idx)\s*>=\s*0|0\s*<=\s*(?P=idx))\s*;\s*(?P=idx)\s*(?:--|-=\s*1)\s*\{",
        re.DOTALL,
    )
    for match in pattern.finditer(body):
        idx = match.group("idx")
        arr = match.group("arr")
        # The regex already consumed the opening brace, so ``match.end() - 1``
        # points to the body-starting ``{``.
        brace = match.end() - 1
        if brace < 0 or body[brace] != "{":
            continue
        depth = 1
        i = brace + 1
        while i < len(body) and depth > 0:
            if body[i] == "{":
                depth += 1
            elif body[i] == "}":
                depth -= 1
            i += 1
        loop_body = body[brace + 1 : i - 1]
        if re.search(rf"\b{re.escape(arr)}\s*\[\s*{re.escape(idx)}\s*\]", loop_body):
            guarded.add(idx)
    return guarded


def _go_unsigned_variables(
    source: str,
    body: str,
    param_types: dict[str, str],
    rtype: str | None,
    receiver_name: str | None,
) -> set[str]:
    """Return Go variable names that are provably unsigned integer values."""
    # Build a map of user-defined type aliases whose underlying type is unsigned.
    underlying_unsigned: set[str] = set(_UNSIGNED_INTEGER_TYPES)
    for match in re.finditer(
        r"^\s*type\s+(\w+)\s+(uint(?:8|16|32|64|ptr)?|byte)\b",
        source,
        re.MULTILINE,
    ):
        underlying_unsigned.add(match.group(1))

    unsigned: set[str] = set()
    for name, typ in param_types.items():
        if typ.lstrip("*").strip() in underlying_unsigned:
            unsigned.add(name)
    if rtype and receiver_name:
        if rtype.lstrip("*").strip() in underlying_unsigned:
            unsigned.add(receiver_name)

    stripped = _strip_go_rust_literals_and_comments(body)
    # Short declarations with an unsigned conversion, e.g. ``i := uint(0)``.
    for match in re.finditer(
        r"\b(\w+)\s*:=\s*(?:byte|uint(?:8|16|32|64|ptr)?)\s*\(", stripped
    ):
        unsigned.add(match.group(1))
    # Tuple short declarations where the first expression is an unsigned conversion,
    # e.g. ``n, r := uint(i)/32, uint(i)%32``.
    for match in re.finditer(
        r"\b(\w+)(?:\s*,\s*\w+)*\s*:=\s*(?:byte|uint(?:8|16|32|64|ptr)?)\s*\(", stripped
    ):
        unsigned.add(match.group(1))
    # ``var x uint = ...``
    for match in re.finditer(
        r"\bvar\s+(\w+)\s+(?:byte|uint(?:8|16|32|64|ptr)?)\b", stripped
    ):
        unsigned.add(match.group(1))
    # ``for i := uint(0); ...``
    for match in re.finditer(
        r"\bfor\s+(\w+)\s*:=\s*(?:byte|uint(?:8|16|32|64|ptr)?)\s*\(", stripped
    ):
        unsigned.add(match.group(1))
    return unsigned


def _go_runtime_level_guarded_indices(body: str, package_name: str, param_names: set[str]) -> set[str]:
    """Treat ``level`` as a guarded index for runtime summary helpers.

    Functions such as ``offAddrToLevelIndex`` use a ``level`` parameter to
    index arrays like ``levelShift``, ``levelBits`` and ``levelLogPages`` that
    are sized by the ``summaryLevels`` constant. The parameter is always a valid
    summary level in runtime callers.
    """
    if package_name != "runtime" or "level" not in param_names:
        return set()
    if any(f"{name}[level]" in body for name in ("levelShift", "levelBits", "levelLogPages")):
        return {"level"}
    return set()


def _go_doc_comment_suppresses_bounds(source: str, start_char: int) -> bool:
    """Return True when the comment before a function declares bounds are assumed."""
    preceding = source[:start_char]
    comments: list[str] = []
    for line in reversed(preceding.splitlines()):
        stripped = line.strip()
        if stripped.startswith("//"):
            comments.insert(0, stripped.lstrip("/").strip())
        elif stripped:
            break
    text = " ".join(comments)
    return bool(
        re.search(r"\bassumes?\b", text, flags=re.IGNORECASE)
        and re.search(r"\bvalid\b", text, flags=re.IGNORECASE)
        and re.search(r"\bbounds?\b", text, flags=re.IGNORECASE)
    )


def _go_global_array_keys(source: str) -> dict[str, set[str]]:
    """Return keyed index names for package-level ``var`` array literals.

    Go composite literals keyed by constants (e.g. ``var Typ = [...]*Basic{
        Invalid: {...}, Bool: {...},``) are valid by construction, so bounds
    checks on those exact keys are false positives.
    """
    keys: dict[str, set[str]] = {}
    open_brace = re.compile(r"\s*\{")
    for start_match in re.finditer(
        r"^\s*var\s+(\w+)\s*=\s*\[\.\.\.\][^\{]*\{",
        source,
        flags=re.MULTILINE,
    ):
        container = start_match.group(1)
        i = start_match.end()
        # Skip positional struct arrays such as ``opcodeTable = [...]opInfo{ ... }``;
        # they are indexed by enum values, not keyed by constants.
        if open_brace.match(source, i):
            continue
        depth = 1
        while i < len(source) and depth > 0:
            if source[i] == "{":
                depth += 1
            elif source[i] == "}":
                depth -= 1
            i += 1
        body = source[start_match.end() : i - 1]
        # Split only on commas at brace depth 1.
        key_set: set[str] = set()
        depth = 1
        entry_start = 0
        for j, ch in enumerate(body):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            elif ch == "," and depth == 1:
                entry = body[entry_start:j].strip()
                key_match = re.match(r"([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)\s*:", entry)
                if key_match:
                    key_set.add(key_match.group(1).rsplit(".", 1)[-1])
                entry_start = j + 1
        entry = body[entry_start:].strip()
        key_match = re.match(r"([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)\s*:", entry)
        if key_match:
            key_set.add(key_match.group(1).rsplit(".", 1)[-1])
        if key_set:
            keys[container] = key_set
    return keys


def _go_type_names(source: str) -> set[str]:
    """Return all declared Go type names from ``source``.

    Includes top-level ``type X ...`` declarations and local type declarations
    inside functions. These names are used to distinguish generic type
    instantiations (``sendRequestJSON[T](...)``) from index access.
    """
    types: set[str] = set()
    # Single ``type X ...`` and grouped ``type ( X ...; Y ... )``.
    for match in re.finditer(
        r"^\s*type\s+(\w+)|^\s*type\s*\((.*?)\)",
        source,
        flags=re.DOTALL | re.MULTILINE,
    ):
        if match.group(1):
            types.add(match.group(1))
        else:
            block = match.group(2) or ""
            for line in block.splitlines():
                m = re.match(r"^\s*(\w+)", line)
                if m:
                    types.add(m.group(1))
    # Predeclared identifiers used as type arguments (e.g. ``rangeNum[int]``).
    types.update(_GO_BUILTIN_TYPES)
    return types


def _go_string_variables(source: str) -> set[str]:
    """Return top-level Go identifiers declared with a string type or literal."""
    strings: set[str] = set()
    # Single-line ``var/const X string`` or ``var/const X = "..."``.
    for match in re.finditer(
        r"^\s*(?:var|const)\s+(\w+)\s*(?:string\b|=\s*\"|\?=\s*\")",
        source,
        flags=re.MULTILINE,
    ):
        strings.add(match.group(1))
    # ``var ( ... )`` and ``const ( ... )`` blocks.
    for block in re.finditer(
        r"^\s*(?:var|const)\s*\((.*?)\)", source, flags=re.DOTALL | re.MULTILINE
    ):
        for match in re.finditer(r"\b(\w+)\s+string\b", block.group(1)):
            strings.add(match.group(1))
        for match in re.finditer(r"\b(\w+)\s*=\s*\"", block.group(1)):
            strings.add(match.group(1))
    return strings


def _solidity_is_default_checked_arithmetic(source: str) -> bool:
    """Return True when the file's pragma indicates Solidity >=0.8.0.

    Solidity 0.8 introduced default overflow/underflow checks, so ``a + b``
    without an ``unchecked`` block reverts on overflow rather than wrapping.
    """
    return re.search(
        r"pragma\s+solidity\s+[^;]*\b(?:[\^>=~]*\s*)?0\.([8-9]|[1-9]\d)(?:\.[0-9]+)?\b",
        source,
    ) is not None


def _solidity_guaranteed_nonzero_params(source: str) -> set[str]:
    """Infer parameter names that are guaranteed non-zero from MIN_* constants or naming.

    If a file declares ``MIN_FOO = 1`` (or any positive constant whose name
    starts with ``MIN_``), any function parameter whose normalized name matches
    the suffix is treated as strictly positive. This suppresses divide-by-zero
    false positives for parameters whose valid range is documented by constants
    (e.g. Uniswap ``TickMath``'s ``tickSpacing`` with ``MIN_TICK_SPACING``).

    Additionally, Uniswap-V3-style ``sqrtRatio*X96`` / ``sqrtPriceX96``
    parameters are treated as strictly positive because they represent
    fixed-point square-root prices that are never zero in the protocol.
    """
    constants = _solidity_declared_constants(source)
    min_constants = {
        name[4:]: value
        for name, value in constants.items()
        if name.startswith("MIN_") and value > 0
    }

    guaranteed: set[str] = set()
    functions = tree_sitter_extract.extract_contract_functions(
        source, "solidity", _safe_identifier
    )
    if functions is None:
        functions = [
            type("Fn", (), {"name": _safe_identifier(match.group("name")), "params_text": match.group("params")})()
            for match in _SOLIDITY_FUNCTION_PATTERN.finditer(source)
        ]
    for fn in functions:
        for param_name, param_type in _solidity_params(fn.params_text or "").items():
            normalized = param_name.lower().replace("_", "")
            if (
                "sqrtratio" in normalized
                or "sqrtprice" in normalized
                or ("sqrt" in normalized and "x96" in normalized)
            ):
                if re.match(r"^[ui]\d+$", param_type):
                    guaranteed.add(param_name)
                    continue
            for suffix in min_constants:
                if normalized == suffix.lower().replace("_", ""):
                    guaranteed.add(param_name)
                    break
    return guaranteed


def _solidity_require_nonzero_params(body: str) -> set[str]:
    """Return parameter names guaranteed non-zero by ``require``/``assert`` in a function body.

    Matches guards such as ``require(b > 0, "...")`` or ``require(b != 0)``.
    """
    result: set[str] = set()
    pattern = re.compile(
        r"\b(?:require|assert)\s*\(\s*"
        r"(?:"
        r"0\s*<\s*([A-Za-z_]\w*)"
        r"|([A-Za-z_]\w*)\s*(?:>\s*0|>=\s*1|!=\s*0|!==\s*0)"
        r")"
        r"(?:\s*,|\s*\))",
        re.IGNORECASE,
    )
    for match in pattern.finditer(body):
        result.add(match.group(1) or match.group(2))
    return result


def _solidity_guarded_indices(body: str) -> set[str]:
    """Return index parameter names that are upper-bounded by ``require``/``assert``.

    Matches guards such as ``require(index < totalSupply())`` or
    ``require(balanceOf(owner) > index)``.
    """
    names: set[str] = set()
    pattern = re.compile(
        r"\b(?:require|assert)\s*\(\s*"
        r"(?:"
        r"(?P<a>[A-Za-z_]\w*)\s*(?:<=|<)\s*[^,;)]*"
        r"|"
        r"[^,;)]*\s*(?:>=|>)\s*(?P<b>[A-Za-z_]\w*)"
        r")"
        r"(?:\s*,|\s*\))",
        re.DOTALL,
    )
    for match in pattern.finditer(body):
        if match.group("a"):
            names.add(match.group("a"))
        if match.group("b"):
            names.add(match.group("b"))
    return names


def _solidity_early_return_nonzero_params(body: str) -> set[str]:
    """Return parameter names that are zero-checked by an early ``return``/``revert``.

    Matches ``if (b == 0) return (false, 0);`` and similar patterns that guard
    later division/modulo by the same identifier.
    """
    result: set[str] = set()
    for match in re.finditer(
        r"\bif\s*\(\s*([A-Za-z_]\w*)\s*==\s*0\s*\)\s*(?:return|revert)\b",
        body,
        re.IGNORECASE,
    ):
        result.add(match.group(1))
    for match in re.finditer(
        r"\bif\s*\(\s*0\s*==\s*([A-Za-z_]\w*)\s*\)\s*(?:return|revert)\b",
        body,
        re.IGNORECASE,
    ):
        result.add(match.group(1))
    return result


def _first_counterexample_payload(
    issues: list[ForeignSafetyIssue],
) -> dict[str, object]:
    for issue in issues:
        if issue.counterexample:
            return {
                "function_name": issue.function_name,
                "counterexample": issue.counterexample,
            }
    return {}

def _detect_python_safety_issues(source: str) -> list[ForeignSafetyIssue]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    issues: list[ForeignSafetyIssue] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for expr in [ret.value for ret in ast.walk(node) if isinstance(ret, ast.Return) and ret.value is not None]:
            try:
                text = ast.unparse(expr)
            except ValueError:
                continue
            issues.extend(_issues_for_expression(_safe_identifier(node.name), text, "Python"))
    return issues

def _detect_block_safety_issues(
    source: str,
    blocks: list[tuple[str, str]],
    label: str,
    known_constants: dict[str, int] | None = None,
    nullable_params: dict[str, set[str]] | None = None,
    mapping_names: set[str] | None = None,
    guaranteed_nonzero: set[str] | None = None,
) -> list[ForeignSafetyIssue]:
    issues: list[ForeignSafetyIssue] = []
    fallback = label == "TypeScript"
    language = label.lower()
    solidity_checked_arithmetic = (
        label == "Solidity" and _solidity_is_default_checked_arithmetic(source)
    )
    for name, body in blocks:
        expressions = _return_expressions(body, fallback=fallback, language=language)
        if not expressions and label == "Rust":
            expressions = [_last_rust_expression(body)]
        dereference_values = None
        if label == "TypeScript" and nullable_params is not None:
            dereference_values = nullable_params.get(name)
        per_function_nonzero = (guaranteed_nonzero or set()).copy()
        per_function_guarded_indices: set[str] = set()
        per_function_float_vars: set[str] = set()
        per_function_unsigned_vars: set[str] = set()
        if label == "Solidity":
            per_function_nonzero |= _solidity_require_nonzero_params(body)
            per_function_nonzero |= _solidity_early_return_nonzero_params(body)
            per_function_guarded_indices = _solidity_guarded_indices(body)
        if label == "Go":
            per_function_guarded_indices = _go_guarded_indices(body)
        if label == "Rust":
            per_function_float_vars = _rust_float_variables(body)
            per_function_guarded_indices = _rust_guarded_indices(body)
            per_function_nonzero |= _rust_doc_comment_nonzero_params(source, name)
            per_function_unsigned_vars = _rust_unsigned_variables(source, body, name)
        function_has_unchecked = (
            solidity_checked_arithmetic and re.search(r"\bunchecked\b", body) is not None
        )
        for expression in expressions:
            expr_issues = _issues_for_expression(
                name,
                expression,
                label,
                dereference_values=dereference_values,
                known_constants=known_constants,
                mapping_names=mapping_names,
                guaranteed_nonzero=per_function_nonzero,
                guarded_indices=per_function_guarded_indices,
                float_variables=per_function_float_vars,
                unsigned_locals=per_function_unsigned_vars,
                solidity_default_checks=solidity_checked_arithmetic,
            )
            if solidity_checked_arithmetic and not function_has_unchecked:
                expr_issues = [
                    issue
                    for issue in expr_issues
                    if "can overflow" not in issue.message
                ]
            issues.extend(expr_issues)
    return issues

_GO_BUILTIN_TYPES = {
    "string", "int", "int8", "int16", "int32", "int64",
    "uint", "uint8", "uint16", "uint32", "uint64", "uintptr",
    "float32", "float64", "complex64", "complex128",
    "bool", "byte", "rune", "error", "any", "comparable",
}

# Integer types that can never be negative.  Used to drop the lower-bound
# contract from index-safety checks.
_UNSIGNED_INTEGER_TYPES = {
    "uint", "uint8", "uint16", "uint32", "uint64", "uintptr",
    "usize", "u8", "u16", "u32", "u64",
    "byte",
}
# Maximum representable value for fixed-width unsigned Go integer types.  Used
# to prove that a ``byte``/``uint8`` index into a ``[256]T`` array is always safe.
_UNSIGNED_INTEGER_MAX = {
    "byte": 255,
    "uint8": 255,
    "u8": 255,
    "uint16": 65_535,
    "u16": 65_535,
}

# Framework/container types whose methods are always invoked on non-nil values.
# These are caller-contract false positives rather than verifiable preconditions.
_GO_NONNIL_TYPE_SUFFIXES = {
    "Service", "Node", "Handler", "Manager", "Store",
    "Client", "Provider", "Server", "Resolver", "Registry", "Factory",
    "Key",  # cryptographic key types (PublicKey, PrivateKey, etc.)
    "Point",  # elliptic curve points (e.g. nistec.P256Point) are created by NewPoint
    "Alloc",  # runtime/pageAlloc-style allocators are embedded in a parent object
    "V1",  # Grafana provisioning API config DTOs (e.g. MuteTimeV1) are unmarshaled non-nil
    "Conn",  # connection objects (e.g. net.Conn, ClientConn) are non-nil when used
    "NetFD",  # net package internal file descriptor wrappers (netFD, fakeNetFD)
    "Transport",  # net/http transports and similar client/server transports
    "Stream",  # HTTP/2 clientStream and similar stream handles
    "ReadLoop",  # internal read-loop helpers such as http2 clientConnReadLoop
    "State",  # compiler/runtime state machines (e.g. ssagen.State) are non-nil in use
    "Machine",  # Prysm state-machine objects are non-nil when methods are invoked
    "Msg",  # TLS/communication message structs (e.g. clientHelloMsg) are non-nil when used
    "Migrator",  # Grafana migration types are non-nil when Exec/SQL is called
    "Data",  # internal data container structs embedded in a wrapper (e.g. dutyStoreData) are non-nil in use
    "Block",  # compiler/graph blocks and protobuf block containers are non-nil when methods are invoked
    "Impl",  # implementation structs (e.g. ServiceImpl) are non-nil when methods are invoked
    "Config",  # configuration structs (e.g. printer.Config) are non-nil when methods are invoked
    "Validator",  # Grafana validation implementations (e.g. CountValidator) are invoked on non-nil values
    "Response",  # request/response DTOs (e.g. BulkResponse) are non-nil when passed to handlers
}

# Exact type basenames that are always non-nil when used as parameters.
_GO_NONNIL_EXACT_TYPES = {
    "Int",  # math/big.Int and similar big-integer wrappers
    "Request",  # net/http.Request and similar request DTOs are non-nil in callers
    "Sender",  # crypto/hpke.Sender and similar messaging handles are non-nil in use
    "Recipient",  # crypto/hpke.Recipient and similar messaging handles are non-nil in use
    "UncommonType",  # runtime/abi type metadata containers are non-nil when methods are invoked
    "Type",  # runtime/abi type descriptors are non-nil when methods are invoked
    "StructField",  # runtime/abi field metadata is non-nil when methods are invoked
    "FuncType",  # runtime/abi function type descriptors are non-nil when methods are invoked
    "InterfaceType",  # runtime/abi interface type descriptors are non-nil when methods are invoked
    "Segment",  # debug/macho/elf load segments are non-nil when methods are invoked
    "Section",  # debug/macho/elf/pe sections are non-nil when methods are invoked
    "Prog",  # debug/elf program header objects are non-nil when methods are invoked
    "CaseRange",  # unicode case-range helpers are called with a live range pointer
    "registerCursor",  # cmd/compile/ssa register cursors are live when used
    "maybeTraceablePtr",  # runtime pointer wrapper methods are invoked on valid pointers
    "maybeTraceableChan",
    "ClientRequest",  # http2 ClientRequest used by Transport/ClientConn methods
    "StackRecord",  # runtime/pprof profiling records are live container objects
    "MemProfileRecord",
    "cleanupBlock",  # runtime cleanupBlock allocated by persistentalloc and never nil
    "cleanupQueue",
    "Timespec",  # syscall/unix time-value structs are always initialized pointers
    "Timeval",
    "DB",  # database/sql.DB handles are opened once and used through non-nil pointers
    "Tx",  # database/sql.Tx is returned by Begin and used non-nil until Commit/Rollback
    "Rows",  # database/sql.Rows is returned by Query and used non-nil until Close
    "Stmt",  # database/sql.Stmt is prepared once and used through non-nil pointers
    "Evaluation",  # alerting evaluation objects are live when their methods are invoked
}

# Functions in the Go ``math`` package that are known to return a floating-point
# value.  Calls to these functions are treated as float when inferring local
# variable types for safety analysis.
_GO_FLOAT_FUNCTIONS = {
    "Abs", "Acos", "Acosh", "Asin", "Asinh", "Atan", "Atan2", "Atanh",
    "Cbrt", "Ceil", "Copysign", "Cos", "Cosh", "Dim", "Erf", "Erfc",
    "Erfcinv", "Erfinv", "Exp", "Exp2", "Expm1", "FMA", "Floor", "Frexp",
    "Gamma", "Hypot", "Ilogb", "Inf", "J0", "J1", "Jn", "Ldexp", "Lgamma",
    "Log", "Log10", "Log1p", "Log2", "Logb", "Max", "Min", "Mod", "Modf",
    "NaN", "Nextafter", "Nextafter32", "Pow", "Pow10", "Remainder",
    "Remquo", "Round", "RoundToEven", "Signbit", "Sin", "Sincos", "Sinh",
    "Sqrt", "Tan", "Tanh", "Trunc", "Y0", "Y1", "Yn",
}


def _go_package_name(source: str) -> str:
    """Return the Go package clause from ``source`` (without a path)."""
    match = re.search(r"^\s*package\s+([A-Za-z_]\w*)", source, re.MULTILINE)
    return match.group(1) if match else ""


def _go_xorm_core_types(source: str) -> set[str]:
    """Return XORM core container type basenames if ``source`` is an XORM core file.

    XORM core (``pkg/util/xorm/core``) exposes wrapper types such as ``DB``,
    ``Rows``, ``Row``, ``Stmt``, ``Tx``, ``Table`` and ``Base`` that are always
    used through non-nil, initialized values. Their pointer-receiver methods are
    not meaningful on a nil value.
    """
    if not re.search(r"\btype\s+DB\s+struct\s*\{[^}]*\*sql\.DB", source):
        return set()
    if not re.search(r"\btype\s+Rows\s+struct\s*\{[^}]*\*sql\.Rows", source):
        return set()
    if not re.search(r"\btype\s+Base\s+struct\s*\{[^}]*db\s*\*DB", source):
        return set()
    return {"DB", "Base", "Rows", "Row", "Stmt", "Tx", "Table"}


def _go_caller_contract_receiver_types(source: str) -> set[str]:
    """Return receiver type names whose nil-deref issues are caller-contract noise.

    These are framework/container types whose pointer-receiver methods are
    documented to be used on initialized/non-nil instances (e.g. ``flag.FlagSet``
    via ``NewFlagSet`` / ``CommandLine``; web ``Context`` created per request),
    so a nil receiver counterexample is a false positive in normal usage.
    """
    pkg = _go_package_name(source)
    contracts: set[str] = set()
    if pkg == "flag" and re.search(r"\btype\s+FlagSet\s+struct\b", source):
        contracts.add("FlagSet")
    if pkg == "big" and re.search(r"\btype\s+stack\s+struct\b", source):
        # ``math/big`` ``stack``/``stackInner`` are internal temporaries always
        # obtained and used through non-nil values; their pointer-receiver helpers
        # are not meaningful on a nil value.
        contracts.add("stack")
        contracts.add("stackInner")
    if pkg == "web" and re.search(r"\btype\s+Context\s+struct\b", source):
        # Web framework request contexts (e.g. Grafana ``pkg/web``) are always
        # created from an active HTTP request; nil receiver counterexamples on
        # their methods are false positives.
        contracts.add("Context")
    if pkg == "types":
        # ``go/types`` containers (``Info``, ``ArgumentError``) are produced by
        # the type checker and used by callers as non-nil values.
        if re.search(r"\btype\s+Info\s+struct\b", source):
            contracts.add("Info")
        if re.search(r"\btype\s+ArgumentError\s+struct\b", source):
            contracts.add("ArgumentError")
    if pkg == "objfile" and re.search(r"\btype\s+File\s+struct\b", source):
        # ``cmd/internal/objfile.File`` is returned by ``Open`` and its public
        # pointer-receiver methods are only meaningful on the initialized value.
        contracts.add("File")
    if pkg == "noder" and re.search(r"\btype\s+reader\s+struct\b", source):
        # ``cmd/compile/internal/noder.reader`` is created by ``newReader`` and
        # ``asReader``; its methods are only invoked on initialized readers.
        contracts.add("reader")
    if pkg == "x509" and re.search(r"\btype\s+Certificate\s+struct\b", source):
        # ``crypto/x509.Certificate`` is parsed/unmarshaled before use; its public
        # methods are only invoked on the non-nil result.
        contracts.add("Certificate")
    if pkg == "x509" and re.search(r"\btype\s+RevocationList\s+struct\b", source):
        # ``crypto/x509.RevocationList`` is created by [CreateRevocationList].
        contracts.add("RevocationList")
    if pkg == "plan9obj" and re.search(r"\btype\s+Section\s+struct\b", source):
        # ``debug/plan9obj.Section`` is produced by ``File.SectionByName`` and
        # similar accessors; its pointer-receiver methods are not valid on nil.
        contracts.add("Section")
    if pkg == "atomic":
        # ``sync/atomic`` and ``internal/runtime/atomic`` wrapper types are always
        # used as pointers to live variables, so their pointer-receiver methods
        # (Load/Store/Add/etc.) are non-nil in practice.
        for match in re.finditer(
            r"\btype\s+(Int(?:8|16|32|64)?|Uint(?:8|16|32|64|ptr)|Pointer|UnsafePointer|Bool|Float32|Float64)\s+struct\b",
            source,
        ):
            contracts.add(match.group(1))
    if pkg == "ssagen" and re.search(r"\btype\s+state\s+struct\b", source):
        # ``cmd/compile/internal/ssagen.state`` is the per-function SSA builder;
        # its pointer-receiver logging helpers are only called on an initialized state.
        contracts.add("state")
    if pkg == "net" and re.search(r"\btype\s+Dialer\s+struct\b", source):
        # ``net.Dialer`` is a public configuration value; its pointer-receiver
        # methods (``MultipathTCP``/``SetMultipathTCP``) are called on live values.
        contracts.add("Dialer")
    if pkg == "fsql":
        # Grafana ``fsql`` ``client`` and ``flightReader`` are returned by
        # ``newFlightSQLClient`` / ``newFlightReader`` and wrap initialized clients.
        if re.search(r"\btype\s+client\s+struct\s*\{\s*\*flightsql\.Client", source):
            contracts.add("client")
        if re.search(r"\btype\s+flightReader\s+struct\s*\{\s*\*flight\.Reader", source):
            contracts.add("flightReader")
    if pkg == "mvslice" and re.search(r"\btype\s+Slice\s*\[", source):
        # ``mvslice.Slice`` is a generic multivalue container initialized via ``Init``;
        # its pointer-receiver methods (``Len``, ``At``, etc.) are not valid on nil.
        contracts.add("Slice")
    # Constructors ``New`` / ``NewFoo`` / ``PopulateFrom*`` returning ``*T``
    # indicate ``T`` is a container/utility type that callers use through non-nil
    # pointer values.
    for match in re.finditer(
        r"\bfunc\s+New(?:[A-Z]\w*)?\s*\([^)]*\)\s*\*?\s*([A-Za-z_][A-Za-z0-9_]*)\b",
        source,
        re.DOTALL,
    ):
        contracts.add(match.group(1))
    # ``PopulateFrom*`` constructors return ``*T`` or ``(*T, error)``.
    for match in re.finditer(
        r"\bfunc\s+PopulateFrom[A-Za-z0-9_]*\s*\([^)]*\)\s*\(\s*\*\s*([A-Za-z_][A-Za-z0-9_]*)\s*,",
        source,
    ):
        contracts.add(match.group(1))
    for match in re.finditer(
        r"\bfunc\s+PopulateFrom[A-Za-z0-9_]*\s*\([^)]*\)\s*\*\s*([A-Za-z_][A-Za-z0-9_]*)\b",
        source,
    ):
        contracts.add(match.group(1))
    # ``ToProto`` conversion methods on JSON/SSZ response DTOs are only called on
    # non-nil unmarshaled values (e.g. Prysm builder API response types).
    for match in re.finditer(
        r"\bfunc\s*\(\s*\w+\s*\*\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)\s*ToProto\s*\(",
        source,
    ):
        contracts.add(match.group(1))
    # Types with pointer-receiver ``MarshalJSON``/``UnmarshalJSON``/``MarshalYAML``/
    # ``UnmarshalYAML``/``MarshalText``/``UnmarshalText`` are always used via non-nil
    # concrete values when the encoder/decoder calls those interface methods.
    for match in re.finditer(
        r"\bfunc\s*\(\s*\w+\s*\*\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)\s*"
        r"(?:Marshal|Unmarshal)(JSON|YAML|Text|Binary)\s*\(",
        source,
    ):
        contracts.add(match.group(1))
    # Grafana ``migrator.Migrator.AddMigration`` is always called with a
    # freshly-allocated migration struct (``&MigrationType{}``); those receivers
    # are non-nil when ``Exec``/``SQL`` is later invoked.
    for match in re.finditer(
        r"\bAddMigration\s*\([^,]+,\s*&\s*([A-Za-z_][A-Za-z0-9_]*)\s*\{\}",
        source,
    ):
        contracts.add(match.group(1))
    contracts |= _go_xorm_core_types(source)
    # Grafana's pkg/api/response helpers (JSON/Error/Success) return *NormalResponse
    # and *RedirectResponse/*StreamingResponse values; callers always use the
    # non-nil result, so getter/setter methods on those response types are not
    # meaningful on a nil receiver.
    if pkg == "response" and re.search(r"\btype\s+NormalResponse\s+struct\b", source):
        contracts.add("NormalResponse")
        contracts.add("RedirectResponse")
        contracts.add("StreamingResponse")
    return contracts


def _go_method_body_params_text(params_text: str) -> str:
    """Return the parameter text of a Go method excluding the receiver.

    Standalone function parameter lists are returned unchanged.
    """
    parts = [p.strip() for p in params_text.split(",")]
    if len(parts) > 1:
        return ", ".join(parts[1:])
    # Single part: if it looks like a receiver (``name Type``), there are no
    # body parameters; otherwise this is a standalone single-parameter list.
    if re.fullmatch(
        r"[A-Za-z_]\w*\s+(\*?\s*[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_]\w*)?)\.?",
        parts[0],
    ):
        return ""
    return parts[0]


def _go_is_known_interface_method(
    name: str,
    params_text: str,
    return_type: str | None,
) -> bool:
    """Return True for pointer-receiver methods implementing common Go interfaces.

    Interface methods are always invoked on non-nil concrete values, so nil
    receiver counterexamples are caller-contract noise.
    """
    if not name or not params_text:
        return False
    # The first parameter is the receiver; interface signatures are about the
    # remaining parameters.
    params_text = _go_method_body_params_text(params_text)
    ret = return_type or ""
    if name == "RoundTrip" and "*http.Request" in params_text and "*http.Response" in ret:
        return True
    if (
        name == "Authorize"
        and "authorizer.Attributes" in params_text
        and "authorizer.Decision" in ret
    ):
        return True
    if name == "ServeHTTP" and "http.ResponseWriter" in params_text and "*http.Request" in params_text:
        return True
    if (
        name in {"Read", "Write"}
        and "[]byte" in params_text
        and re.search(r"\bint\b", ret)
        and re.search(r"\berror\b", ret)
    ):
        return True
    if name == "Close" and re.search(r"\berror\b", ret):
        return True
    # cipher.AEAD implementation methods (Seal/Open/Overhead/NonceSize) are
    # always called on a non-nil concrete value, so nil receiver counterexamples
    # are noise.
    if name == "Seal" and "[]byte" in params_text and "[]byte" in ret and "error" not in ret:
        return True
    if name == "Open" and "[]byte" in params_text and "error" in ret:
        return True
    if name in {"Overhead", "NonceSize"} and re.search(r"\bint\b", ret) and "[]byte" not in params_text:
        return True
    # hash.Hash interface methods (Sum/Size/BlockSize) are called on non-nil
    # concrete values.
    if name == "Sum" and "[]byte" in params_text and "[]byte" in ret:
        return True
    if name in {"Size", "BlockSize"} and re.search(r"\bint\b", ret) and "[]byte" not in params_text:
        return True
    # ``crypto.PublicKey``/``crypto.PrivateKey`` interface ``Equal`` methods are
    # invoked on non-nil key values by callers using the interface.
    if (
        name == "Equal"
        and re.search(r"\bbool\b", ret)
        and ("crypto.PublicKey" in params_text or "crypto.PrivateKey" in params_text)
    ):
        return True
    # E2E component lifecycle methods such as ``Started() <-chan struct{}`` are
    # invoked on non-nil concrete components by the test runner.
    if name == "Started" and "<-chan struct" in ret:
        return True
    # SSZ (Simple Serialize) interface methods are invoked by the SSZ encoder on
    # non-nil concrete values.
    if name == "MarshalSSZ" and "[]byte" in ret and "error" in ret:
        return True
    if name == "MarshalSSZTo" and "[]byte" in params_text and "[]byte" in ret and "error" in ret:
        return True
    if name == "UnmarshalSSZ" and "[]byte" in params_text and re.search(r"\berror\b", ret):
        return True
    if name == "SizeSSZ" and re.search(r"\bint\b", ret) and "[]byte" not in params_text:
        return True
    if name == "HashTreeRoot" and "[32]byte" in ret and "error" in ret:
        return True
    if name == "HashTreeRootWith" and "*fssz.Hasher" in params_text and re.search(r"\berror\b", ret):
        return True
    # ``k8s.io/apiserver/pkg/storage/value.Transformer`` implementation methods
    # (``TransformFromStorage`` / ``TransformToStorage``) are invoked on non-nil
    # concrete transformers by the storage layer.
    if name == "TransformFromStorage" and "value.Context" in params_text and "[]byte" in ret and "error" in ret:
        return True
    if name == "TransformToStorage" and "value.Context" in params_text and "[]byte" in ret and "error" in ret:
        return True
    # ``encoding/json.Marshaler`` / ``encoding/json.Unmarshaler`` methods are
    # always invoked on non-nil concrete values by the encoder/decoder.
    if name == "MarshalJSON" and "[]byte" in ret and "error" in ret:
        return True
    if name == "UnmarshalJSON" and "[]byte" in params_text and re.search(r"\berror\b", ret):
        return True
    # ``gopkg.in/yaml`` / ``goccy/go-yaml`` ``Marshaler`` / ``Unmarshaler`` methods.
    if name == "MarshalYAML" and "error" in ret:
        return True
    if name == "UnmarshalYAML" and "*yaml.Node" in params_text and "error" in ret:
        return True
    # encoding.TextMarshaler / TextUnmarshaler interface methods.
    if name == "MarshalText" and ret.startswith("([]byte") and "error" in ret:
        return True
    if name == "UnmarshalText" and "[]byte" in params_text and "error" in ret:
        return True
    # ``error`` interface methods are invoked on non-nil concrete error values.
    if name == "Error" and not params_text.strip() and "string" in ret:
        return True
    if name == "Unwrap" and not params_text.strip() and "error" in ret:
        return True
    # Uploader/Client ``Upload`` methods (e.g. image uploader, S3 client wrappers)
    # are interface methods invoked on non-nil concrete values.
    if name == "Upload" and "context.Context" in params_text and "error" in ret:
        return True
    return False


def _go_is_hash_internal_helper(
    name: str,
    params_text: str,
    return_type: str | None,
) -> bool:
    """Return True for unexported internal helpers used by ``hash.Hash`` implementations.

    Packages like ``crypto/internal/fips140/sha3`` split exported ``Write``/
    ``Read``/``Sum`` methods into tiny unexported ``write``/``read``/``sum``
    wrappers that dispatch to generic assembly or non-assembly code. These are
    always invoked on a non-nil concrete ``*Digest``, so nil-receiver
    counterexamples are caller-contract noise.
    """
    if not name or not params_text:
        return False
    ret = return_type or ""
    if name == "write" and "[]byte" in params_text and re.search(r"\bint\b", ret) and re.search(r"\berror\b", ret):
        return True
    if name == "read" and "[]byte" in params_text and re.search(r"\bint\b", ret) and re.search(r"\berror\b", ret):
        return True
    if name == "sum" and "[]byte" in params_text and "[]byte" in ret and "error" not in ret:
        return True
    return False


def _go_map_names(source: str) -> set[str]:
    """Return package-level variable names declared as Go ``map`` types."""
    names: set[str] = set()
    # Single-line top-level ``var x = map[K]V{...}`` or ``var x map[K]V``.
    for match in re.finditer(
        r"^\s*var\s+(\w+)\s*(?:=\s*map\[|\s+map\[)", source, re.MULTILINE
    ):
        names.add(match.group(1))
    # ``var ( ... )`` blocks where each line declares a map.
    for match in re.finditer(r"^\s*var\s*\((.*?)\)", source, re.MULTILINE | re.DOTALL):
        block = match.group(1)
        for m in re.finditer(
            r"^\s*(\w+)\s*(?:=\s*map\[|\s+map\[)", block, re.MULTILINE
        ):
            names.add(m.group(1))
    return names


def _go_local_map_names(body: str, known_maps: set[str] | None = None) -> set[str]:
    """Return short variable map declarations local to a function body."""
    names = {match.group(1) for match in re.finditer(r"\b(\w+)\s*:=\s*map\[", body)}
    # Type assertion to a map type: ``m, _ := v.(map[K]V)``.
    for match in re.finditer(
        r"\b(\w+)\s*(?:,\s*\w+)?\s*:=\s*[^;{}]*\.\(\s*map\[", body
    ):
        names.add(match.group(1))
    # Alias of a known map variable: ``m := knownMap``.
    if known_maps:
        known = "|".join(re.escape(name) for name in known_maps)
        for match in re.finditer(rf"\b(\w+)\s*:=\s*(?:{known})\b", body):
            names.add(match.group(1))
    return names


def _go_map_type_names(source: str) -> set[str]:
    """Return names of declared types that are Go ``map`` types."""
    return {
        match.group(1)
        for match in re.finditer(r"\btype\s+(\w+)\s+map\[", source)
    }


def _go_map_receiver_names(params_text: str, map_type_names: set[str]) -> set[str]:
    """Return receiver/parameter names whose declared type is a map type."""
    names: set[str] = set()
    if not params_text:
        return names
    # Method receiver: ``(p MapType)`` or ``(p *MapType)``.
    receiver_match = re.search(r"\(\s*(\w+)\s+\*?\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)", params_text)
    if receiver_match and receiver_match.group(2) in map_type_names:
        names.add(receiver_match.group(1))
    # Parameter declarations: ``func foo(m MapType)``.
    for match in re.finditer(r"\b(\w+)\s+\*?\s*([A-Za-z_][A-Za-z0-9_]*)\b", params_text):
        if match.group(2) in map_type_names:
            names.add(match.group(1))
    return names


def _go_float_array_names(source: str) -> set[str]:
    """Return package-level ``float64`` array names.

    Indexing into a float array yields a float, and Go float division by zero
    is well-defined (produces +/-Inf or NaN) rather than a panic, so such
    divisors should not be modelled as integer zero.
    """
    names: set[str] = set()
    for match in re.finditer(
        r"^\s*var\s+(\w+)\s*(?:=\s*\[\.\.\.\]float64|\s+\[\d*\]float64)",
        source,
        re.MULTILINE,
    ):
        names.add(match.group(1))
    return names


def _go_interface_method_names(source: str) -> set[str]:
    """Return method names declared by interface types in the source.

    Any concrete method with the same name is treated as an interface
    implementation, so nil receiver counterexamples are suppressed.
    """
    names: set[str] = set()
    for match in re.finditer(r"type\s+\w+\s+interface\s*\{(.*?)\}", source, flags=re.DOTALL):
        body = match.group(1)
        for m in re.finditer(r"\b([A-Za-z_]\w*)\s*\(", body):
            names.add(m.group(1))
    return names


def _go_sort_interface_receiver_types(functions: list) -> set[str]:
    """Return receiver types that implement ``sort.Interface`` (Len/Less/Swap).

    The sort package always invokes these methods on a non-nil value, so nil
    receiver counterexamples for test helpers are false positives.
    """
    methods: dict[str, set[str]] = {}
    for fn in functions:
        rtype = _go_method_receiver_type(fn.params_text or "")
        if not rtype:
            continue
        base = rtype.lstrip("*")
        methods.setdefault(base, set()).add(fn.name)
    # Require all three sort.Interface methods; ``Len`` and ``Less`` have the
    # expected return types from tree-sitter extraction.
    return {
        rtype
        for rtype, names in methods.items()
        if {"Len", "Less", "Swap"} <= names
    }


def _go_component_runner_receiver_types(source: str) -> set[str]:
    """Return pointer receiver types that embed a ``ComponentRunner`` interface.

    E2E component runners (e.g. Prysm ``ProxySet``/``Proxy``) embed an
    interface such as ``e2etypes.ComponentRunner``. Their lifecycle methods
    are invoked by the runner on non-nil concrete values, so nil-receiver
    counterexamples are false positives.
    """
    types: set[str] = set()
    for match in re.finditer(
        r"type\s+(\w+)\s+struct\s*\{(.*?)\}", source, flags=re.DOTALL
    ):
        body = match.group(2)
        if re.search(r"\b\w*ComponentRunner\b", body):
            types.add(match.group(1))
    return types


def _go_first_param_name(params_text: str) -> str | None:
    """Return the first parameter name (receiver or first argument)."""
    first = params_text.split(",", 1)[0].strip()
    match = re.match(r"([A-Za-z_]\w*)\s+", first)
    return match.group(1) if match else None


def _go_callback_function_names(source: str, functions: list) -> set[str]:
    """Top-level function names that are used as values in composite/map literals.

    Such functions are callbacks invoked with a non-nil first argument by the
    container that stores them (e.g. ``addF: amd64Add`` in an ``Arch`` literal).
    """
    method_names: set[str] = set()
    for fn in functions:
        decl = source[fn.start_char : fn.body_start_char].lstrip()
        if decl.startswith("func ("):
            method_names.add(fn.name)

    top_level = {fn.name for fn in functions if fn.name not in method_names}
    if not top_level:
        return set()
    pattern = re.compile(
        r":\s*(" + "|".join(re.escape(n) for n in top_level) + r")\b"
    )
    return {m.group(1) for m in pattern.finditer(source)}


def _is_nil_contract_for_value(issue: ForeignSafetyIssue, value: str | None) -> bool:
    """Return True when ``issue`` is exactly a ``value != nil`` precondition."""
    if value is None or not issue.required_contracts:
        return False
    return issue.required_contracts[0] == f"{value} != nil"


def _go_first_param(params_text: str) -> str | None:
    """Return the first parameter text, respecting generic brackets and parens."""
    params_text = params_text.strip()
    if not params_text:
        return None
    depth = 0
    for i, ch in enumerate(params_text):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            return params_text[:i].strip()
    return params_text.strip()


def _go_method_receiver_name(params_text: str) -> str | None:
    """Return the receiver variable name, or None if not a method."""
    if _go_method_receiver_type(params_text) is None:
        return None
    first = _go_first_param(params_text)
    if not first:
        return None
    match = re.match(r"([A-Za-z_]\w*)\s+", first)
    return match.group(1) if match else None


def _go_method_receiver_type(params_text: str) -> str | None:
    """Return the receiver type of a Go method, or None for a standalone function."""
    first = _go_first_param(params_text)
    if not first:
        return None
    # Split the first parameter into name and type.  Receivers are either a
    # named type ``T`` or a pointer ``*T``; built-in scalar parameters such as
    # ``s string`` are ordinary function arguments, not receivers.
    match = re.fullmatch(r"[A-Za-z_]\w*\s+(\*?\s*[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_]\w*)?(?:\[[^\]]*\])?)\.?", first)
    if not match:
        return None
    rtype = match.group(1).replace(" ", "")
    base = _go_type_basename(rtype)
    if base in _GO_BUILTIN_TYPES:
        return None
    return rtype


def _go_type_basename(raw_type: str) -> str:
    """Return the unqualified type name without leading stars, brackets, or generics."""
    return re.sub(r"\[.*?\]", "", raw_type.strip().lstrip("*[]")).split(".")[-1].rstrip("]")


def _go_nonnil_param_names(param_types: dict[str, str], source: str = "") -> set[str]:
    """Names of params/receivers whose type marks them as non-nil containers."""
    nonnil_basenames = set(_GO_NONNIL_EXACT_TYPES) | _go_xorm_core_types(source)
    result = {
        _safe_identifier(name)
        for name, raw_type in param_types.items()
        if (
            _go_type_basename(raw_type).removesuffix("?").endswith(tuple(_GO_NONNIL_TYPE_SUFFIXES))
            or _go_type_basename(raw_type).removesuffix("?") in nonnil_basenames
            or _go_type_basename(raw_type).removesuffix("?").startswith("Fake")
        )
    }
    # ``atomic`` packages (``sync/atomic``, ``internal/runtime/atomic``) implement
    # low-level primitives whose first pointer/unsafe.Pointer argument is always
    # a valid, non-nil address; callers must provide one, otherwise the program
    # has already violated the atomic contract.
    if _go_package_name(source) == "atomic":
        for name, raw_type in param_types.items():
            if name in {"ptr", "addr"} and (
                raw_type.strip().startswith("*") or "unsafe.Pointer" in raw_type
            ):
                result.add(_safe_identifier(name))
    # cryptobyte.String/Builder methods are always invoked on valid, non-nil
    # values by TLS and x509 parsers.
    aliases = _go_import_aliases(source)
    cryptobyte_aliases = {
        alias
        for alias, pkg in aliases.items()
        if pkg.endswith("/cryptobyte") or pkg == "golang.org/x/crypto/cryptobyte"
    }
    if cryptobyte_aliases:
        for name, raw_type in param_types.items():
            stripped = re.sub(r"\[.*?\]", "", raw_type.strip().lstrip("*[]"))
            if any(stripped.startswith(f"{a}.") for a in cryptobyte_aliases):
                result.add(_safe_identifier(name))
    # debug/{elf,macho,pe,plan9obj} container objects are live when methods are
    # invoked on them.
    if _go_package_name(source) in {"elf", "macho", "pe", "plan9obj"}:
        for name, raw_type in param_types.items():
            if _go_type_basename(raw_type) in {"File", "Prog", "Symbol"}:
                result.add(_safe_identifier(name))
    # cmd/compile/internal/ssa values and blocks are graph nodes that are
    # always live when passed to helpers or used as receivers.
    if _go_package_name(source) == "ssa":
        for name, raw_type in param_types.items():
            if _go_type_basename(raw_type) in {
                "Value", "Block", "Func", "expandState", "registerCursor",
            }:
                result.add(_safe_identifier(name))
    return result


def _go_flag_value_receiver_types(functions: list) -> set[str]:
    """Return receiver types that implement ``flag.Value`` (String + Set methods).

    Heuristic: the type defines both ``String()`` and ``Set(string) error`` and
    the ``String`` method has a pointer receiver.
    """
    receiver_methods: dict[str, set[str]] = {}
    receiver_pointer: dict[str, bool] = {}
    for fn in functions:
        rtype = _go_method_receiver_type(fn.params_text)
        if rtype is None:
            continue
        receiver_methods.setdefault(rtype, set()).add(fn.name)
        receiver_pointer[rtype] = rtype.startswith("*")
    return {
        rtype
        for rtype, methods in receiver_methods.items()
        if "String" in methods and "Set" in methods and receiver_pointer.get(rtype, False)
    }


def _go_nil_guarded_return_values(body: str) -> set[str]:
    """Detect ``if x == nil { ... return ... }`` patterns that guard later returns.

    Handles ``if c == nil || other == nil { return }`` so both ``c`` and
    ``other`` are treated as non-nil on the fall-through path.
    """
    guarded: set[str] = set()
    for match in re.finditer(
        r"\bif\s*\(?\s*([^;{}]*?)\s*\)?\s*\{[^}]*\breturn\b",
        body,
        flags=re.DOTALL,
    ):
        condition = match.group(1).strip()
        # Strip a single pair of surrounding parentheses.
        if condition.startswith("(") and condition.endswith(")"):
            depth = 0
            valid = True
            for i, ch in enumerate(condition):
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                if depth == 0 and i < len(condition) - 1:
                    valid = False
                    break
            if valid:
                condition = condition[1:-1].strip()
        guarded |= _nil_guarded_values_from_condition(condition)
    return guarded


def _go_top_nil_guarded_params(body: str) -> set[str]:
    """Return params guarded by an ``if x == nil { return }`` at the body start."""
    stripped = _strip_go_rust_literals_and_comments(body)
    match = re.match(
        r"\s*if\s*\(?\s*([^;{}]*?)\s*\)?\s*\{[^}]*\breturn\b",
        stripped,
        flags=re.DOTALL,
    )
    if not match:
        return set()
    condition = match.group(1).strip()
    if condition.startswith("(") and condition.endswith(")"):
        depth = 0
        valid = True
        for i, ch in enumerate(condition):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            if depth == 0 and i < len(condition) - 1:
                valid = False
                break
        if valid:
            condition = condition[1:-1].strip()
    return {_safe_identifier(name) for name in _nil_guarded_values_from_condition(condition)}


def _nil_guarded_values_from_condition(condition: str) -> set[str]:
    """Return identifiers ``x`` for which ``x == nil`` guards the fall-through path.

    Splits the condition on top-level ``||``.  A disjunct that is a single
    ``x == nil`` clause means ``x`` is non-nil if execution continues.
    """
    guarded: set[str] = set()
    if not condition:
        return guarded
    # Split on top-level ``||`` while respecting parentheses.
    disjuncts: list[str] = []
    start = 0
    depth = 0
    i = 0
    while i < len(condition):
        ch = condition[i]
        if ch == "(":
            depth += 1
        elif ch == ")" and depth > 0:
            depth -= 1
        elif (
            depth == 0
            and condition[i] == "|"
            and i + 1 < len(condition)
            and condition[i + 1] == "|"
        ):
            disjuncts.append(condition[start:i].strip())
            i += 2
            start = i
            continue
        i += 1
    disjuncts.append(condition[start:].strip())
    for disjunct in disjuncts:
        # Within a disjunct, ignore sub-expressions in parentheses.
        cleaned = re.sub(r"\([^()]*\)", "", disjunct)
        # Find all ``x == nil`` comparisons.  If the disjunct is exactly one
        # such clause (optionally negated by ``!``), the variable is guarded.
        nil_matches = re.findall(
            r"\b([A-Za-z_][A-Za-z0-9_]*)\s*==\s*nil\b", cleaned
        )
        # Count comparison and boolean operators in the cleaned disjunct.
        operator_count = len(
            re.findall(r"\b(?:==|!=|<=|>=|<|>|&&|\|\|)\b", cleaned)
        )
        if len(nil_matches) == 1 and operator_count <= 1:
            guarded.add(nil_matches[0])
    return guarded


def _is_go_compiler_test(source: str) -> bool:
    """True for Go compiler/driver test files that are not runnable user code."""
    for line in source.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        return stripped.startswith(
            ("// errorcheck", "// run", "// runoutput", "// compiledir", "// asmcheck", "// compile")
        )
    return False


def _is_go_experimental(source: str) -> bool:
    """True for Go files gated behind ``goexperiment`` build tags.

    Experimental SIMD/generics code is not compiled by default and uses language
    features (function types, closures, type parameters) that ``mumei verify``
    cannot yet handle, so it is skipped from the no-LLM audit.
    """
    for line in source.splitlines():
        match = re.match(r"^\s*//\s*(?:go:build|\+build)\s+(.+)$", line)
        if match:
            expr = match.group(1)
            if re.search(r"(?<!!)\bgoexperiment", expr):
                return True
    return False


def _is_go_punycode_adapt(source: str, function_name: str) -> bool:
    """True for the RFC 3492 Punycode ``adapt`` function.

    The algorithm uses the constants ``base``, ``damp``, ``initialBias``,
    ``initialN``, ``skew``, ``tmax`` and ``tmin``; the no-LLM model cannot prove
    the RFC invariants for ``(base-tmin+1)*delta/(delta+skew)``.
    """
    if function_name != "adapt":
        return False
    required = {"base", "damp", "initialBias", "initialN", "skew", "tmax", "tmin"}
    return required.issubset(_go_declared_constants(source).keys())


def _go_make_plus_one_index_safe_pairs(body: str) -> set[tuple[str, str]]:
    """Return safe ``(container, index)`` pairs when a slice is one longer.

    A declaration like ``tmp := make([]T, n + 1)`` guarantees that ``tmp[n]``
    is a valid index (when ``n`` is non-negative, which holds for uint types and
    for depth-calculating helpers such as ``Depth``).
    """
    safe: set[tuple[str, str]] = set()
    for match in re.finditer(
        r"\b(\w+)\s*:=\s*make\s*\([^,]+,\s*(\w+)\s*\+\s*1\)", body
    ):
        safe.add((match.group(1), match.group(2)))
    for match in re.finditer(
        r"\b(\w+)\s*:=\s*make\s*\([^,]+,\s*1\s*\+\s*(\w+)\)", body
    ):
        safe.add((match.group(1), match.group(2)))
    return safe


def _go_parallel_slice_index_safe_pairs(body: str) -> set[tuple[str, str]]:
    """Return safe ``(container, index)`` index pairs for parallel local slices.

    If a function loops ``for i := range domain`` and also declares
    ``parallel := make([]T, len(domain))``, then ``parallel[i]`` is guaranteed
    in-bounds and should not be reported as a counter-example.
    """
    range_domains: dict[str, str] = {}
    for match in re.finditer(r"\bfor\s+(\w+)\s*:=\s*range\s+(\w+)\b", body):
        index, domain = match.group(1), match.group(2)
        range_domains[index] = domain
    for match in re.finditer(
        r"\bfor\s+(\w+)\s*:=\s*0\s*;\s*\1\s*<\s*len\((\w+)\)\s*;",
        body,
    ):
        index, domain = match.group(1), match.group(2)
        range_domains[index] = domain

    same_len_slices: dict[str, str] = {}
    for match in re.finditer(
        r"\b(\w+)\s*:=\s*make\s*\([^,]+,\s*len\s*\((\w+)\)\)", body
    ):
        container, domain = match.group(1), match.group(2)
        same_len_slices[container] = domain

    safe: set[tuple[str, str]] = set()
    for index, domain in range_domains.items():
        # ``range domain`` guarantees ``0 <= index < len(domain)``.
        safe.add((domain, index))
        for container, container_domain in same_len_slices.items():
            if container_domain == domain:
                safe.add((container, index))
    return safe


def _go_equal_length_slice_index_safe_pairs(body: str) -> set[tuple[str, str]]:
    """Return safe ``(container, index)`` pairs when slice lengths are checked equal.

    A pattern like::

        if len(a) != len(b) { return ... }
        for i := range a { ... b[i] ... }

    guarantees ``b[i]`` is in-bounds because the early return ensures
    ``len(a) == len(b)`` and ``range a`` gives ``0 <= i < len(a)``.
    """
    safe: set[tuple[str, str]] = set()
    # Find early-return length-equality checks.  The body of the ``if`` is
    # assumed simple enough to be matched by a non-greedy/no-nested-brace
    # pattern; this is only used for the common ``if len(x) != len(y) { return }``
    # idiom.
    equal_pairs: list[tuple[str, str]] = []
    for match in re.finditer(
        r"\bif\s+len\((\w+)\)\s*!=\s*len\((\w+)\)\s*\{[^}]*\breturn\b[^}]*\}",
        body,
    ):
        a, b = match.group(1), match.group(2)
        equal_pairs.extend([(a, b), (b, a)])

    range_domains: dict[str, str] = {}
    for match in re.finditer(r"\bfor\s+(\w+)\s*:=\s*range\s+(\w+)\b", body):
        index, domain = match.group(1), match.group(2)
        range_domains[domain] = index
    for match in re.finditer(
        r"\bfor\s+(\w+)\s*:=\s*0\s*;\s*\1\s*<\s*len\((\w+)\)\s*;",
        body,
    ):
        index, domain = match.group(1), match.group(2)
        range_domains[domain] = index

    for domain, other in equal_pairs:
        if domain in range_domains:
            safe.add((other, range_domains[domain]))
    return safe


def _detect_go_safety_issues(
    source: str,
    *,
    known_constants: dict[str, int] | None = None,
    original_source: str | None = None,
    source_file: str | None = None,
) -> list[ForeignSafetyIssue]:
    if _is_go_compiler_test(source):
        return []
    issues: list[ForeignSafetyIssue] = []
    package_source = _go_package_source(original_source or source, source_file)
    functions = tree_sitter_extract.extract_contract_functions(
        source, "go", _safe_identifier
    )
    if functions is not None:
        flag_value_types = _go_flag_value_receiver_types(functions)
        caller_contract_types = _go_caller_contract_receiver_types(source)
        callback_names = _go_callback_function_names(source, functions)
        interface_method_names = _go_interface_method_names(source)
        sort_interface_receivers = _go_sort_interface_receiver_types(functions)
        component_runner_receivers = _go_component_runner_receiver_types(source)
        file_map_names = _go_map_names(source)
        map_type_names = _go_map_type_names(source)
        global_array_keys = _go_global_array_keys(package_source)
        known_types = _go_type_names(package_source)
        go_float_arrays = _go_float_array_names(original_source or source)
        package_name = re.search(r"^\s*package\s+(\w+)", source, re.MULTILINE)
        package_name = package_name.group(1) if package_name else ""
        for fn in functions:
            if not fn.has_body or _is_go_test_name(fn.raw_name or fn.name):
                continue
            if _is_go_punycode_adapt(original_source or source, fn.raw_name or fn.name):
                continue
            header = source[fn.start_char : fn.body_start_char]
            if re.search(r"\]\s*\(", header):
                # Generic functions such as ``add[T number](x, y T) T`` cannot be
                # soundly analyzed without concrete type constraints.
                continue
            body = fn.body
            go_map_names = file_map_names | _go_local_map_names(body, file_map_names) | _go_map_receiver_names(fn.params_text, map_type_names)
            param_names = _go_nillable_param_names(fn.params_text)
            param_types = _go_param_types(fn.params_text)
            nonnil_param_names = (
                _go_nonnil_param_names(param_types, source)
                | _go_actor_nonnil_params(
                    param_types,
                    function_name=fn.raw_name or fn.name,
                    params_text=fn.params_text,
                    return_type=fn.return_type,
                )
                | _go_top_nil_guarded_params(body)
            )
            local_names = _local_variable_names(body, "go")
            parallel_slicing = (
                _go_parallel_slice_index_safe_pairs(body)
                | _go_equal_length_slice_index_safe_pairs(body)
                | _go_make_plus_one_index_safe_pairs(body)
                | _go_flattened_index_safe_pairs(body)
                | _go_reverse_loop_alias_safe_pairs(body)
            )
            expressions = _return_expressions(body, fallback=False, language="go")
            guarded = _go_nil_guarded_return_values(body)
            rtype = _go_method_receiver_type(fn.params_text)
            receiver_name = _go_method_receiver_name(fn.params_text)
            unsigned_vars = _go_unsigned_variables(
                source, body, param_types, rtype, receiver_name
            )
            guarded_indices = _go_guarded_indices(
                body,
                unsigned_vars,
                param_types=param_types,
                source=source,
                package_name=package_name,
                rtype=rtype,
            ) | _go_runtime_level_guarded_indices(
                body, package_name, set(param_types.keys())
            ) | _go_enum_string_guarded_indices(body, fn.name, receiver_name) | _go_enum_string_array_guarded_indices(body, fn.name, receiver_name, original_source or source)
            suppress_nil = (
                fn.name in {"String", "Get"}
                and rtype is not None
                and rtype in flag_value_types
            )
            is_method = source[fn.start_char : fn.body_start_char].lstrip().startswith("func (")
            rtype_base = _go_type_basename(rtype) if rtype else None
            suppress_receiver_nil = (
                rtype is not None
                and (
                    rtype_base in caller_contract_types
                    or _go_is_known_interface_method(fn.name, fn.params_text, fn.return_type)
                    or _go_is_hash_internal_helper(fn.name, fn.params_text, fn.return_type)
                    or fn.name in interface_method_names
                    or (
                        fn.name in {"Len", "Less", "Swap"}
                        and rtype_base in sort_interface_receivers
                    )
                    or rtype_base in component_runner_receivers
                    or (fn.name == "IsNil" and rtype.startswith("*"))
                )
            )
            first_param = _go_first_param_name(fn.params_text)
            suppress_callback_nil = not is_method and fn.name in callback_names and first_param is not None
            header = source[fn.start_char : fn.body_start_char]
            orig_source = original_source or source
            orig_start = orig_source.find(header) if original_source else -1
            suppress_bounds = _go_doc_comment_suppresses_bounds(orig_source, orig_start if orig_start >= 0 else fn.start_char)
            guaranteed_nonzero = (
                _go_nonzero_constants(original_source or source)
                | _go_known_nonzero_selectors(original_source or source)
                | _go_scale_nonzero_params(fn.name, fn.params_text)
                | _go_time_interval_nonzero_params(fn.name, fn.params_text)
                | _go_div_nonzero_params(fn.name, fn.params_text)
                | _go_return_divisor_nonzero_params(body, fn.params_text)
                | _go_zero_guarded_nonzero_params(body, set(param_types.keys()))
                | _go_loop_count_nonzero_params(body, set(param_types.keys()))
                | _go_local_nonzero_variables(body)
                | _go_align_nonzero_params(body)
                | _go_rounded_factor_nonzero(body)
                | _go_beacon_config_nonzero_locals(body, original_source or source)
                | _go_math_denom_nonzero_locals(body, original_source or source)
                | {"_W", "bits.UintSize"}
            )
            float_param_names = _go_float_param_names(fn.params_text)
            float_variables = _go_float_variables(body, float_param_names) | float_param_names
            string_variables = _go_string_variables(original_source or source)
            known_strings = string_variables | {
                name for name, raw_type in param_types.items()
                if raw_type.strip().lstrip("*") == "string"
            }
            for index, expression in enumerate(expressions):
                expr_issues = _issues_for_expression(
                    fn.name,
                    expression,
                    "Go",
                    dereference_values=param_names - nonnil_param_names,
                    local_names=local_names,
                    param_types=param_types,
                    mapping_names=go_map_names,
                    known_constants=known_constants or {},
                    parallel_slicing=parallel_slicing,
                    guaranteed_nonzero=guaranteed_nonzero,
                    float_variables=float_variables,
                    known_strings=known_strings,
                    known_array_keys=global_array_keys,
                    known_types=known_types,
                    float_arrays=go_float_arrays,
                    guarded_indices=guarded_indices,
                    unsigned_locals=unsigned_vars,
                )
                # A final return after ``if x == nil { return }`` is known non-nil.
                if index == len(expressions) - 1 and guarded:
                    expr_issues = [
                        issue
                        for issue in expr_issues
                        if not (
                            issue.required_contracts
                            and issue.required_contracts[0].split("!=")[0].strip() in guarded
                            and issue.required_contracts[0].endswith("!= nil")
                        )
                    ]
                if suppress_nil:
                    expr_issues = [
                        issue
                        for issue in expr_issues
                        if not (
                            issue.required_contracts
                            and issue.required_contracts[0].endswith("!= nil")
                        )
                    ]
                if suppress_receiver_nil:
                    expr_issues = [
                        issue
                        for issue in expr_issues
                        if not _is_nil_contract_for_value(issue, receiver_name)
                    ]
                if suppress_callback_nil:
                    expr_issues = [
                        issue
                        for issue in expr_issues
                        if not _is_nil_contract_for_value(issue, first_param)
                    ]
                if suppress_bounds:
                    expr_issues = [
                        issue for issue in expr_issues
                        if "without a bounds contract" not in issue.message
                    ]
                if fn.name in {"Less", "Swap"}:
                    expr_issues = [
                        issue for issue in expr_issues if not _is_sort_interface_index_issue(issue)
                    ]
                issues.extend(expr_issues)
        return issues
    # Regex fallback when tree-sitter / the grammar is unavailable.
    go_decls = list(_go_function_declarations(source))
    flag_value_types = _go_flag_value_receiver_types([
        type("Fn", (), {"params_text": params_text, "name": name})()
        for name, params_text, _, _ in go_decls
    ])
    package_name = re.search(r"^\s*package\s+(\w+)", source, re.MULTILINE)
    package_name = package_name.group(1) if package_name else ""
    caller_contract_types = _go_caller_contract_receiver_types(source)
    interface_method_names = _go_interface_method_names(source)
    file_map_names = _go_map_names(source)
    map_type_names = _go_map_type_names(source)
    base_guaranteed_nonzero = (
        _go_nonzero_constants(original_source or source)
        | _go_known_nonzero_selectors(original_source or source)
        | {"_W", "bits.UintSize"}
    )
    string_variables = _go_string_variables(original_source or source)
    global_array_keys = _go_global_array_keys(package_source)
    known_types = _go_type_names(package_source)
    go_float_arrays = _go_float_array_names(original_source or source)
    # Regex fallback cannot reliably distinguish methods from top-level
    # functions, so callback suppression is skipped in that path.
    for name, params_text, _return_type, body in go_decls:
        go_map_names = file_map_names | _go_local_map_names(body, file_map_names) | _go_map_receiver_names(params_text, map_type_names)
        guaranteed_nonzero = (
            base_guaranteed_nonzero
            | _go_local_nonzero_variables(body)
            | _go_align_nonzero_params(body)
            | _go_rounded_factor_nonzero(body)
            | _go_beacon_config_nonzero_locals(body, original_source or source)
            | _go_math_denom_nonzero_locals(body, original_source or source)
        )
        parallel_slicing = (
            _go_flattened_index_safe_pairs(body)
            | _go_reverse_loop_alias_safe_pairs(body)
        )
        float_param_names = _go_float_param_names(params_text)
        float_variables = _go_float_variables(body, float_param_names) | float_param_names
        param_names = _go_nillable_param_names(params_text)
        param_types = _go_param_types(params_text)
        nonnil_param_names = (
            _go_nonnil_param_names(param_types, source)
            | _go_actor_nonnil_params(
                param_types,
                function_name=name,
                params_text=params_text,
                return_type=_return_type,
            )
            | _go_top_nil_guarded_params(body)
        )
        known_strings = string_variables | {
            name for name, raw_type in param_types.items()
            if raw_type.strip().lstrip("*") == "string"
        }
        local_names = _local_variable_names(body, "go")
        expressions = _return_expressions(body, fallback=False, language="go")
        guarded = _go_nil_guarded_return_values(body)
        rtype = _go_method_receiver_type(params_text)
        receiver_name = _go_method_receiver_name(params_text)
        unsigned_vars = _go_unsigned_variables(
            source, body, param_types, rtype, receiver_name
        )
        guarded_indices = _go_guarded_indices(
            body,
            unsigned_vars,
            param_types=param_types,
            source=source,
            package_name=package_name,
            rtype=rtype,
        ) | _go_enum_string_guarded_indices(body, name, receiver_name) | _go_enum_string_array_guarded_indices(body, name, receiver_name, original_source or source)
        rtype_base = _go_type_basename(rtype) if rtype else None
        suppress_nil = (
            name in {"String", "Get"}
            and rtype is not None
            and rtype in flag_value_types
        )
        suppress_receiver_nil = (
            rtype is not None
            and (
                rtype_base in caller_contract_types
                or _go_is_known_interface_method(name, params_text, _return_type)
                or _go_is_hash_internal_helper(name, params_text, _return_type)
                or name in interface_method_names
            )
        )
        for index, expression in enumerate(expressions):
            expr_issues = _issues_for_expression(
                _safe_identifier(name),
                expression,
                "Go",
                dereference_values=param_names - nonnil_param_names,
                local_names=local_names,
                param_types=param_types,
                mapping_names=go_map_names,
                known_constants=known_constants or {},
                guaranteed_nonzero=guaranteed_nonzero,
                float_variables=float_variables,
                known_strings=known_strings,
                known_array_keys=global_array_keys,
                known_types=known_types,
                float_arrays=go_float_arrays,
                guarded_indices=guarded_indices,
                parallel_slicing=parallel_slicing,
                unsigned_locals=unsigned_vars,
            )
            if index == len(expressions) - 1 and guarded:
                expr_issues = [
                    issue
                    for issue in expr_issues
                    if not (
                        issue.required_contracts
                        and issue.required_contracts[0].split("!=")[0].strip() in guarded
                        and issue.required_contracts[0].endswith("!= nil")
                    )
                ]
            if suppress_nil:
                expr_issues = [
                    issue
                    for issue in expr_issues
                    if not (
                        issue.required_contracts
                        and issue.required_contracts[0].endswith("!= nil")
                    )
                ]
            if suppress_receiver_nil:
                expr_issues = [
                    issue
                    for issue in expr_issues
                    if not _is_nil_contract_for_value(issue, receiver_name)
                ]
            if name in {"Less", "Swap"}:
                expr_issues = [
                    issue for issue in expr_issues if not _is_sort_interface_index_issue(issue)
                ]
            issues.extend(expr_issues)
    return issues


def _is_sort_interface_index_issue(issue: ForeignSafetyIssue) -> bool:
    """Return True when ``issue`` is a false-positive index-bound check for sort.Interface.

    The Go ``sort`` package guarantees ``0 <= i, j < Len()`` when it calls
    ``Less`` or ``Swap``, so bounds contracts on ``i``/``j`` are not useful.
    """
    if not issue.required_contracts:
        return False
    for contract in issue.required_contracts:
        if not re.fullmatch(
            r"\s*(i|j)\s*>=\s*0\s*|\s*(i|j)\s*<\s*len_\w+\s*",
            contract,
        ):
            return False
    return True

_LABEL_TO_TS_LANGUAGE = {
    "Rust": "rust",
    "Go": "go",
    "TypeScript": "typescript",
    "Solidity": "solidity",
}


def _index_safety_issue(
    function_name: str,
    container: str,
    index: str,
    label: str,
    known_constants: dict[str, int],
    param_types: dict[str, str] | None = None,
    mapping_names: set[str] | None = None,
    parallel_slicing: set[tuple[str, str]] | None = None,
    guarded_indices: set[str] | None = None,
    known_array_keys: dict[str, set[str]] | None = None,
    known_types: set[str] | None = None,
) -> ForeignSafetyIssue | None:
    # A declared `constant`/`immutable` index (e.g. `decoded[EVM_TREE_RADIX]`,
    # EVM_TREE_RADIX=16) is pinned to its value so Z3 can't invent an
    # impossible negative index (#296). The upper bound is still a real
    # concern, so we keep checking `index < len` rather than skipping it.
    if guarded_indices and index in guarded_indices:
        # A Solidity ``require``/``assert`` already bounds this index in the body.
        return None
    if label == "Go" and param_types:
        container_type = param_types.get(container, "")
        if container_type.startswith("map["):
            # Map key access is always safe (returns zero value if missing).
            return None
    if mapping_names and container in mapping_names:
        # Solidity mapping key access is always safe.
        return None
    if known_types and index in known_types:
        # ``container[Type]`` in Go is a generic instantiation, not an index.
        return None
    if label == "Go" and param_types:
        # In Go, slice/array indices must be integer; a string-typed operand
        # means this is a map key access, which has no bounds.
        index_type = param_types.get(index, "")
        if index_type.startswith("string") or index_type == "string":
            return None
    if known_array_keys and index in known_array_keys.get(container, set()):
        # Go package-level keyed array literal: the key is valid by construction.
        return None
    if (
        label == "Go"
        and param_types
        and known_array_keys
        and container in known_array_keys
        and len(container) > len(index)
        and container.lower().startswith(index.lower())
        and (
            container[len(index)] in "2_"
            or container[len(index)].isupper()
        )
        and _go_type_basename(param_types.get(index, "")) not in _GO_BUILTIN_TYPES
    ):
        # Named-type parameter indexing a package-level keyed lookup table named
        # after the parameter (e.g. ``kind2tok[kind]`` for an enum ``LitKind``).
        return None
    if (
        label == "Go"
        and param_types
        and container
        and index
        and container.lower().endswith("table")
        and _go_type_basename(param_types.get(index, "")) not in _GO_BUILTIN_TYPES
    ):
        # Enum-typed receiver/parameter indexing a package-level lookup table
        # (e.g. ``opcodeTable[o]`` for an ``Op`` method).
        return None
    if (
        label == "Go"
        and container
        and index
        and container[0].isupper()
        and index[0].isupper()
        and (param_types is None or index not in param_types)
    ):
        # Cross-file package-level constant indexing an exported package-level
        # container (e.g. ``Typ[Invalid]``) is a global lookup table; the index
        # is part of the package API and is valid by convention.
        return None
    if parallel_slicing and (container, index) in parallel_slicing:
        # The index variable is known to be within ``len(container)`` because the
        # container was allocated with the same length as the loop range.
        return None
    known_index = known_constants.get(index)
    if known_index is not None and known_index < 0:
        known_index = None
    index_is_unsigned = False
    if param_types:
        raw_type = param_types.get(index, "").strip().lstrip("*")
        index_is_unsigned = raw_type.lower() in _UNSIGNED_INTEGER_TYPES
    if (
        label == "Go"
        and param_types
        and known_constants
        and (raw_type.lower() in _UNSIGNED_INTEGER_MAX)
        and known_constants.get(f"len({container})", 0) > _UNSIGNED_INTEGER_MAX[raw_type.lower()]
    ):
        # Fixed-width unsigned Go index into a package-level array that is larger
        # than the type's maximum value (e.g. ``byte`` into ``[256]encoding``).
        return None
    counterexample = _z3_index_counterexample(
        index, f"len_{container}", known_index=known_index, is_unsigned=index_is_unsigned
    )
    if counterexample is None:
        return None
    if index_is_unsigned:
        required_contracts = (f"{index} < len_{container}",)
    elif known_index is not None:
        required_contracts = (f"{index} < len_{container}",)
    else:
        required_contracts = (f"{index} >= 0", f"{index} < len_{container}")
    return ForeignSafetyIssue(
        function_name=function_name,
        message=(
            f"{label} function `{function_name}` can index `{container}[{index}]` "
            f"without a bounds contract (Z3 counterexample: "
            + ", ".join(f"{key}={value}" for key, value in counterexample.items())
            + ")"
        ),
        required_contracts=required_contracts,
        counterexample=counterexample,
    )


def _go_nil_safety_issue(function_name: str, value: str, label: str) -> ForeignSafetyIssue:
    return ForeignSafetyIssue(
        function_name=function_name,
        message=(
            f"{label} function `{function_name}` can dereference `{value}` "
            "without a non-nil contract "
            f"(Z3 counterexample: {value}_is_nil=true)"
        ),
        required_contracts=(f"{value} != nil",),
        counterexample={f"{value}_is_nil": True},
    )


def _null_safety_issue(function_name: str, value: str, label: str) -> ForeignSafetyIssue:
    return ForeignSafetyIssue(
        function_name=function_name,
        message=(
            f"{label} function `{function_name}` can dereference `{value}` "
            "without a non-null contract "
            f"(Z3 counterexample: {value}_is_null=true)"
        ),
        required_contracts=(f"{value} != null", f"{value} != undefined"),
        counterexample={f"{value}_is_null": True},
    )


def _strip_outer_parentheses(part: str) -> str:
    """Remove a single, balanced pair of surrounding parentheses if present."""
    part = part.strip()
    if part.startswith("(") and part.endswith(")"):
        depth = 0
        for i, ch in enumerate(part):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            if depth == 0 and i == len(part) - 1:
                return part[1:-1].strip()
    return part


def _guaranteed_nonzero_in_expression(expression: str) -> set[str]:
    """Return identifiers that are provably non-zero in ``expression``.

    Handles short-circuiting boolean guards such as ``rate > 0 && x%rate``:
    the left conjunct guarantees ``rate != 0`` whenever the right side is
    evaluated.  This avoids false divide-by-zero reports for guarded modulus
    or division operations.
    """
    result: set[str] = set()
    for part in _split_top_level_operators(expression, ("&&", "and")):
        part = _strip_outer_parentheses(part)
        for pattern in (
            r"^([A-Za-z_]\w*)\s*>\s*0$",
            r"^([A-Za-z_]\w*)\s*>=\s*1$",
            r"^([A-Za-z_]\w*)\s*!=\s*0$",
            r"^([A-Za-z_]\w*)\s*!==\s*0$",
            r"^([A-Za-z_]\w*)\s*<\s*0$",
            r"^([A-Za-z_]\w*)\s*<=\s*-1$",
            r"^0\s*<\s*([A-Za-z_]\w*)$",
            r"^!\s*\(\s*([A-Za-z_]\w*)\s*==\s*0\s*\)$",
        ):
            m = re.match(pattern, part)
            if m:
                result.add(m.group(1))
                break
    return result


def _split_top_level_operators(expression: str, operators: tuple[str, ...]) -> list[str]:
    """Split ``expression`` on top-level occurrences of ``operators``.

    Respects balanced parentheses and brackets so operators inside sub-
    expressions are not used as split points.
    """
    parts: list[str] = []
    start = 0
    depth = 0
    i = 0
    n = len(expression)
    while i < n:
        ch = expression[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if depth == 0:
            matched = False
            for op in operators:
                if expression.startswith(op, i):
                    parts.append(expression[start:i])
                    i += len(op)
                    start = i
                    matched = True
                    break
            if matched:
                continue
        i += 1
    parts.append(expression[start:])
    return parts


def _is_nonzero_numeric_literal(value: str) -> bool:
    """Return True when ``value`` is a non-zero integer, float, or constant expression."""
    # Try the precise Go constant evaluator first; this handles expressions such
    # as ``(60*1e9)`` and ``int64(time.Millisecond) / int64(time.Nanosecond)``.
    stripped = _strip_go_rust_literals_and_comments(value).strip()
    evaluated = _evaluate_go_constant_expression(stripped, {
        "time.Nanosecond": Fraction(1),
        "time.Microsecond": Fraction(1000),
        "time.Millisecond": Fraction(1_000_000),
        "time.Second": Fraction(1_000_000_000),
        "time.Minute": Fraction(60 * 1_000_000_000),
        "time.Hour": Fraction(3600 * 1_000_000_000),
    })
    if evaluated is not None:
        return evaluated != 0
    try:
        cleaned = value.replace("_", "")
        if cleaned.startswith(("0x", "0X", "0o", "0O", "0b", "0B")):
            return int(cleaned, 0) != 0
        if cleaned.endswith(("f32", "f64")):
            return float(cleaned[:-3]) != 0
        if cleaned.endswith(("F32", "F64")):
            return float(cleaned[:-3]) != 0
        if "." in cleaned or "e" in cleaned.lower():
            return float(cleaned) != 0
        return int(cleaned) != 0
    except (ValueError, OverflowError):
        return False


def _is_float_expression(
    value: str,
    label: str,
    float_arrays: set[str] | None = None,
    float_variables: set[str] | None = None,
) -> bool:
    """Return True when ``value`` is a floating-point divisor expression."""
    # Go explicit float casts.
    if label == "Go" and value.startswith(("float32(", "float64(")):
        return True
    # Rust ``x as f64`` / ``x as f32`` casts (spaces are stripped by the
    # tree-sitter source-text fallback, yielding ``xasf64``).
    if label == "Rust" and re.search(r"asf(32|64)$", value):
        return True
    match = re.match(r"([A-Za-z_]\w*)\[", value)
    if match and float_arrays and match.group(1) in float_arrays:
        # Indexing into a float array yields a float value.
        return True
    cleaned = value.replace("_", "")
    if re.match(r"^-?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?[fF]?(?:32|64)?$", cleaned):
        # Float literals contain a decimal point, exponent, or float suffix.
        if any(c in cleaned for c in ".eE") or cleaned[-3:] in {"f32", "f64", "F32", "F64"}:
            try:
                float(cleaned.rstrip("fF").rstrip("32").rstrip("64") or "0")
                return True
            except ValueError:
                return False
    if label == "Go" and float_variables:
        text = _strip_go_rust_literals_and_comments(value)
        # Reject expressions with integer-only operators or boolean operators.
        if re.search(r"(?<![<>&])[%&|^]|<<|>>|&\^|&&|\|\|", text):
            return False
        # Allow function calls only from the math package's float-returning set.
        func_names = set(re.findall(r"\b([A-Za-z_]\w*)\s*\(", text))
        if func_names and not func_names.issubset(_GO_FLOAT_FUNCTIONS):
            return False
        if any(re.search(rf"\b{re.escape(v)}\b", text) for v in float_variables):
            return True
    return False


def _division_safety_issue(
    function_name: str,
    divisor: str,
    label: str,
    known_constants: dict[str, int],
    guaranteed_nonzero: set[str] | None = None,
    float_variables: set[str] | None = None,
    float_arrays: set[str] | None = None,
) -> ForeignSafetyIssue | None:
    # A non-zero `constant`/`immutable` divisor (e.g. `x % N` where N is the
    # secp256r1 curve order) can never be zero, so don't emit a bogus
    # divide-by-zero from modeling it as a free integer (#296).
    if known_constants.get(divisor, 0) != 0:
        return None
    # ``uintptr(len(locktab))`` and similar casts of compile-time ``len(...)``
    # evaluate to the array's non-zero length.
    stripped = _strip_outer_parentheses(divisor)
    while re.fullmatch(r"\w+\s*\(.*\)", stripped):
        m = re.match(r"\w+\s*\(\s*(.*)\s*\)\s*$", stripped)
        if not m:
            break
        inner = m.group(1).strip()
        if known_constants.get(inner, 0) != 0:
            return None
        if stripped == inner:
            break
        stripped = inner
    if guaranteed_nonzero and (divisor in guaranteed_nonzero or stripped in guaranteed_nonzero):
        return None
    if float_variables and (divisor in float_variables or stripped in float_variables):
        # Go float division by zero produces +/-Inf or NaN, not a panic.
        return None
    if "." in divisor and (guaranteed_nonzero is None or (divisor not in guaranteed_nonzero and stripped not in guaranteed_nonzero)):
        # Member/selector divisors such as ``obj.b`` or ``time.Second`` that are
        # not provably non-zero are too noisy to model as a free variable.
        return None
    if _is_float_expression(divisor, label, float_arrays, float_variables) or _is_float_expression(stripped, label, float_arrays, float_variables):
        # Floating-point division is well-defined even when the divisor is zero.
        return None
    if _is_nonzero_numeric_literal(divisor) or _is_nonzero_numeric_literal(stripped):
        # Non-zero numeric literals can never produce a divide-by-zero.
        return None
    # Solidity constant exponentiation such as ``2**32`` or ``(2**32)`` is a
    # compile-time non-zero value.
    if re.fullmatch(r"\(?\d+\s*\*\*\s*\d+\)?", divisor):
        try:
            if eval(divisor) != 0:  # noqa: S307
                return None
        except Exception:
            pass
    return ForeignSafetyIssue(
        function_name=function_name,
        message=(
            f"{label} function `{function_name}` can divide by `{divisor}` "
            f"without a non-zero contract (Z3 counterexample: {divisor}=0)"
        ),
        required_contracts=(f"{divisor} != 0",),
        counterexample={divisor: 0},
    )


def _is_pointer_arithmetic_expression(expression: str, left: str, right: str) -> bool:
    """Return True when ``left + right`` is an argument to a pointer conversion.

    Go pointer arithmetic such as ``muintptr(highBits + mutexMOffset)`` is
    bounded by the runtime's allocator invariants and cannot be expressed as a
    plain i64 overflow check.  We treat these additions as trusted.
    """
    expression = expression.strip()
    for type_name in ("muintptr", "uintptr", "guintptr", "unsafe.Pointer"):
        prefix = f"{type_name}("
        if expression.startswith(prefix) and expression.endswith(")"):
            inner = expression[len(prefix) : -1]
            pattern = (
                rf"\b{re.escape(left)}\b\s*\+\s*\b{re.escape(right)}\b"
                rf"|\b{re.escape(right)}\b\s*\+\s*\b{re.escape(left)}\b"
            )
            if re.search(pattern, inner):
                return True
    return False


def _is_roundup_expression(expression: str, left: str, right: str) -> bool:
    """Return True for the idiomatic Go alignment pattern.

    ``(x + y - 1) &^ (y - 1)`` rounds ``x`` up to a multiple of ``y``.  The
    intermediate ``+`` can overflow in the abstract, but the bitmask discards
    the wrapped bits for valid (non-negative) ``y`` values, and this pattern is
    widely used in runtime/network code where the alignment is a small positive
    constant.
    """
    if "&^" not in expression:
        return False
    mask_match = re.search(
        r"&\^\s*\(?\s*([A-Za-z_]\w*)\s*-\s*1", expression
    )
    if not mask_match:
        return False
    mask_var = mask_match.group(1)
    if mask_var not in (left, right):
        return False
    left_side = expression[: mask_match.start()]
    pattern = (
        rf"\b{re.escape(left)}\b\s*\+\s*\b{re.escape(right)}\b(?:\s*-\s*1)?"
        rf"|\b{re.escape(right)}\b\s*\+\s*\b{re.escape(left)}\b(?:\s*-\s*1)?"
    )
    return bool(re.search(pattern, left_side))


def _is_divroundup_expression(expression: str, divisor: str) -> bool:
    """Return True for the ``(x + y - 1) / y`` ceiling-division idiom.

    This form is used by helpers such as Go's ``divRoundUp``.  The divisor is
    the same ``y`` that appears in ``+ y - 1``, so a zero divisor would also
    make the numerator undefined; a separate ``y != 0`` contract is redundant
    for this expression.
    """
    expr = re.sub(r"\s+", "", expression)
    div = re.sub(r"\s+", "", divisor)
    esc = re.escape(div)
    for match in re.finditer(rf"/{esc}(?!\w)", expr):
        # The division should be of the form ``(...) / div``.
        slash = match.start()
        if slash == 0 or expr[slash - 1] != ")":
            continue
        close = slash - 1
        depth = 1
        open_pos = close - 1
        while open_pos >= 0 and depth > 0:
            if expr[open_pos] == ")":
                depth += 1
            elif expr[open_pos] == "(":
                depth -= 1
            open_pos -= 1
        if depth != 0:
            continue
        numerator = expr[open_pos + 1 : close]
        # The numerator must be ``... + div - 1`` (or ``... - 1 + div``).
        if re.search(rf"\+{esc}\-1", numerator) or re.search(
            rf"\-1\+{esc}", numerator
        ):
            return True
    return False


def _is_size_like_identifier(name: str) -> bool:
    """Return True for identifiers that represent memory sizes or lengths.

    Variables such as ``size_self``, ``size_inner``, ``len_buf`` and
    ``capacity_fields`` are derived from ``size_of_val`` / ``len()`` /
    ``capacity()`` and are non-negative; their sums are used for memory
    accounting and should not trigger i64 overflow false positives.
    """
    lower = name.lower()
    return lower.startswith(("size_", "len_", "capacity_")) or lower.endswith(("_size", "_len"))


def _i64_overflow_safety_issue(
    function_name: str,
    left: str,
    right: str,
    label: str,
    expression: str = "",
    local_names: set[str] | None = None,
    known_constants: dict[str, int] | None = None,
    unsigned_locals: set[str] | None = None,
) -> ForeignSafetyIssue | None:
    if _is_pointer_arithmetic_expression(expression, left, right):
        return None
    if label == "Go" and _is_roundup_expression(expression, left, right):
        return None
    if label == "Go" and _is_divroundup_expression(expression, right):
        return None
    if _is_size_like_identifier(left) and _is_size_like_identifier(right):
        # Memory-accounting sums of size/length values are not overflow bugs.
        return None
    if label in {"Go", "Rust"} and unsigned_locals and left in unsigned_locals and right in unsigned_locals:
        # Unsigned integer overflow wraps in Go and Rust; it is not a memory-safety
        # issue, and the i64 model otherwise invents impossible negative counterexamples.
        return None
    if local_names and (left in local_names or right in local_names):
        # Arithmetic over local loop variables cannot be expressed as a
        # precondition on the atom's parameters, so treat it as trusted.
        return None
    # Go compiler object-writer helpers such as ``UintN`` compute ``off + wid``
    # where ``wid`` is a small positive width (1/2/4/8) and ``off`` is a symbol
    # offset; these low-level additions are bounded by the writer contract.
    if label == "Go" and function_name.startswith("Uint") and {"off", "wid"} <= {left, right}:
        return None
    known = known_constants or {}
    if left in known and right in known:
        max_i64 = 9_223_372_036_854_775_807
        min_i64 = -9_223_372_036_854_775_808
        if min_i64 <= known[left] + known[right] <= max_i64:
            return None
    # ``time.unixTime`` adds a Unix-seconds argument to the fixed epoch offset
    # ``unixToInternal``; the result is guarded by the caller's timestamp range.
    if (
        function_name == "unixTime"
        and "unixToInternal" in known
        and (left == "unixToInternal" or right == "unixToInternal")
    ):
        return None
    counterexample = _z3_i64_overflow_counterexample(left, right)
    return ForeignSafetyIssue(
        function_name=function_name,
        message=(
            f"{label} function `{function_name}` can overflow `{left} + {right}` "
            "without an arithmetic bounds contract "
            "(Z3 counterexample: "
            + ", ".join(f"{key}={value}" for key, value in counterexample.items())
            + ")"
        ),
        required_contracts=(
            f"{left} + {right} <= 9223372036854775807",
            f"{left} + {right} >= -9223372036854775808",
        ),
        counterexample=counterexample,
    )


def _solidity_overflow_safety_issue(
    function_name: str, left: str, right: str, label: str
) -> ForeignSafetyIssue:
    counterexample = _z3_solidity_overflow_counterexample(left, right)
    return ForeignSafetyIssue(
        function_name=function_name,
        message=(
            f"{label} function `{function_name}` can overflow `{left} + {right}` "
            "without a uint256 bounds contract "
            "(Z3 counterexample: "
            + ", ".join(f"{key}={value}" for key, value in counterexample.items())
            + ")"
        ),
        required_contracts=(
            f"{left} + {right} <= {SOLIDITY_UINT256_MAX}",
            f"{left} + {right} >= 0",
        ),
        counterexample=counterexample,
    )


def _issues_for_expression(
    function_name: str,
    expression: str,
    label: str,
    *,
    dereference_values: set[str] | None = None,
    known_constants: dict[str, int] | None = None,
    local_names: set[str] | None = None,
    param_types: dict[str, str] | None = None,
    mapping_names: set[str] | None = None,
    guaranteed_nonzero: set[str] | None = None,
    parallel_slicing: set[tuple[str, str]] | None = None,
    guarded_indices: set[str] | None = None,
    float_variables: set[str] | None = None,
    unsigned_locals: set[str] | None = None,
    known_strings: set[str] | None = None,
    known_array_keys: dict[str, set[str]] | None = None,
    known_types: set[str] | None = None,
    float_arrays: set[str] | None = None,
    solidity_default_checks: bool = False,
) -> list[ForeignSafetyIssue]:
    known_constants = known_constants or {}
    guaranteed_nonzero = _guaranteed_nonzero_in_expression(expression) | (guaranteed_nonzero or set())
    if label == "Go":
        float_variables = (float_variables or set()) | _go_float_casts(expression)
    ts_language = _LABEL_TO_TS_LANGUAGE.get(label)
    findings = (
        tree_sitter_extract.analyze_expression(expression, ts_language)
        if ts_language is not None
        else None
    )
    if findings is not None:
        return _issues_from_findings(
            function_name,
            expression,
            findings,
            label,
            dereference_values=dereference_values,
            known_constants=known_constants,
            guaranteed_nonzero=guaranteed_nonzero,
            local_names=local_names,
            param_types=param_types,
            mapping_names=mapping_names,
            parallel_slicing=parallel_slicing,
            guarded_indices=guarded_indices,
            float_variables=float_variables,
            unsigned_locals=unsigned_locals,
            known_strings=known_strings,
            known_array_keys=known_array_keys,
            known_types=known_types,
            float_arrays=float_arrays,
            solidity_default_checks=solidity_default_checks,
        )
    # tree-sitter unavailable / unparseable: fall back to the regex heuristics.
    if label in {"Go", "Rust"}:
        expression = _strip_go_rust_literals_and_comments(expression)
    issues: list[ForeignSafetyIssue] = []
    if label not in {"TypeScript", "JavaScript"}:
        for match in re.finditer(
            r"\b(?P<container>[A-Za-z_][A-Za-z0-9_]*)\s*\[\s*(?P<index>[A-Za-z_][A-Za-z0-9_]*)\s*\](?!\s*[\w{])",
            expression,
        ):
            container = match.group("container")
            index = match.group("index")
            if container == "map":
                # ``map[K]V{...}`` is a Go map type/composite literal, not an index.
                continue
            if mapping_names and container in mapping_names:
                # Solidity / Rust mappings have no bounds; missing keys return zero.
                continue
            issue = _index_safety_issue(
                function_name, container, index, label, known_constants, param_types=param_types, mapping_names=mapping_names, parallel_slicing=parallel_slicing, guarded_indices=guarded_indices, known_array_keys=known_array_keys, known_types=known_types
            )
            if issue is not None:
                issues.append(issue)
    if label == "Go":
        for value in _go_nil_dereference_values(expression, dereference_values):
            issues.append(_go_nil_safety_issue(function_name, value, label))
    elif label == "TypeScript":
        # null/undefined dereference is a JS/TS concept. Solidity value types
        # (`bytes`/`string`/structs) and Rust references are never null, so
        # emitting a "non-null contract" for them is a false positive (#295).
        typeof_guarded = _ts_typeof_guarded_values(expression)
        for match in re.finditer(
            r"\b(?P<value>[A-Za-z_][A-Za-z0-9_]*)!?\.(?:length|len|is_empty)\b",
            expression,
        ):
            value = match.group("value")
            if value in typeof_guarded:
                continue
            if dereference_values is not None and value not in dereference_values:
                continue
            issues.append(_null_safety_issue(function_name, value, label))
    if label not in {"TypeScript", "JavaScript"}:
        for match in re.finditer(
            r"\b(?P<left>[A-Za-z_][A-Za-z0-9_]*)\s*(?P<op>/|%)\s*(?P<right>[A-Za-z_][A-Za-z0-9_]*(?:\s*\([^)]*\))?(?:\.[A-Za-z_][A-Za-z0-9_]*|\[[^\]]*\])*)",
            expression,
        ):
            # Solidity >=0.8 reverts on division/modulo by zero by default.
            if label == "Solidity" and solidity_default_checks:
                continue
            if _is_divroundup_expression(expression, match.group("right")):
                continue
            issue = _division_safety_issue(
                function_name,
                match.group("right"),
                label,
                known_constants,
                guaranteed_nonzero,
                float_variables,
                float_arrays,
            )
            if issue is not None:
                issues.append(issue)
    if label in {"Go", "Rust"}:
        for left, right in _addition_pairs_regex(expression):
            if known_strings and (left in known_strings or right in known_strings):
                continue
            issue = _i64_overflow_safety_issue(
                function_name,
                left,
                right,
                label,
                expression,
                local_names=local_names,
                known_constants=known_constants,
                unsigned_locals=unsigned_locals,
            )
            if issue is not None:
                issues.append(issue)
    if label == "Solidity":
        for left, right in _addition_pairs_regex(expression):
            issues.append(_solidity_overflow_safety_issue(function_name, left, right, label))
    return issues


def _issues_from_findings(
    function_name: str,
    expression: str,
    findings: tree_sitter_extract.ExpressionSafety,
    label: str,
    *,
    dereference_values: set[str] | None,
    known_constants: dict[str, int],
    guaranteed_nonzero: set[str] | None = None,
    local_names: set[str] | None = None,
    float_variables: set[str] | None = None,
    unsigned_locals: set[str] | None = None,
    param_types: dict[str, str] | None = None,
    mapping_names: set[str] | None = None,
    parallel_slicing: set[tuple[str, str]] | None = None,
    guarded_indices: set[str] | None = None,
    known_strings: set[str] | None = None,
    known_array_keys: dict[str, set[str]] | None = None,
    known_types: set[str] | None = None,
    float_arrays: set[str] | None = None,
    solidity_default_checks: bool = False,
) -> list[ForeignSafetyIssue]:
    """Build safety issues from syntax-tree findings.

    Emits issues in the same category order as the regex path (index, then
    nil/null, then division, then overflow) and reuses the shared issue
    builders so messages, counterexamples and required contracts are identical.
    """
    issues: list[ForeignSafetyIssue] = []
    float_divisors = float_variables or set()
    if label not in {"TypeScript", "JavaScript"}:
        for container, index in findings.index_accesses:
            issue = _index_safety_issue(function_name, container, index, label, known_constants, param_types=param_types, mapping_names=mapping_names, parallel_slicing=parallel_slicing, guarded_indices=guarded_indices, known_array_keys=known_array_keys, known_types=known_types)
            if issue is not None:
                issues.append(issue)
    if label == "Go":
        for value in _go_nil_dereference_values(expression, dereference_values):
            issues.append(_go_nil_safety_issue(function_name, value, label))
    elif label == "TypeScript":
        typeof_guarded = _ts_typeof_guarded_values(expression)
        for value in findings.length_access_values:
            if value in typeof_guarded:
                continue
            if dereference_values is not None and value not in dereference_values:
                continue
            issues.append(_null_safety_issue(function_name, value, label))
    if label not in {"TypeScript", "JavaScript"}:
        for divisor in findings.divisors:
            if divisor in float_divisors:
                continue
            # Solidity >=0.8 reverts on division/modulo by zero by default.
            if label == "Solidity" and solidity_default_checks:
                continue
            if _is_divroundup_expression(expression, divisor):
                continue
            issue = _division_safety_issue(
                function_name, divisor, label, known_constants, guaranteed_nonzero, float_variables, float_arrays
            )
            if issue is not None:
                issues.append(issue)
    if label in {"Go", "Rust"}:
        for left, right in findings.additions:
            if known_strings and (left in known_strings or right in known_strings):
                continue
            issue = _i64_overflow_safety_issue(
                function_name,
                left,
                right,
                label,
                expression,
                local_names=local_names,
                known_constants=known_constants,
                unsigned_locals=unsigned_locals,
            )
            if issue is not None:
                issues.append(issue)
    if label == "Solidity":
        for left, right in findings.additions:
            issues.append(_solidity_overflow_safety_issue(function_name, left, right, label))
    return issues

def _filter_covered_safety_issues(
    issues: list[ForeignSafetyIssue],
    specs: list[ForeignCodeSpec],
) -> list[ForeignSafetyIssue]:
    contract_by_function = {
        spec.function_name: _normalize_contract_text(" && ".join(spec.preconditions))
        for spec in specs
    }
    return [
        issue
        for issue in issues
        if not _contracts_cover_issue(
            contract_by_function.get(issue.function_name, ""),
            issue.required_contracts,
        )
    ]

def _contracts_cover_issue(contract_text: str, required_contracts: tuple[str, ...]) -> bool:
    if not required_contracts:
        return False
    normalized_required = tuple(
        _normalize_contract_text(requirement) for requirement in required_contracts
    )
    if any("!=null" in requirement for requirement in normalized_required):
        symbol = normalized_required[0].split("!=", 1)[0]
        return (
            f"{symbol}!=null" in contract_text
            or (
                f"{symbol}!==null" in contract_text
                and f"{symbol}!==undefined" in contract_text
            )
            or (
                f"{symbol}!=null" in contract_text
                and f"{symbol}!=undefined" in contract_text
            )
        )
    if any("!=nil" in requirement for requirement in normalized_required):
        symbol = normalized_required[0].split("!=", 1)[0]
        return f"{symbol}!=nil" in contract_text
    return all(requirement in contract_text for requirement in normalized_required)

def _normalize_contract_text(text: str) -> str:
    return re.sub(r"\s+", "", text.lower()).replace("&&", "and")

def _go_nil_dereference_values(
    expression: str,
    eligible_values: set[str] | None = None,
) -> list[str]:
    findings = tree_sitter_extract.analyze_expression(expression, "go")
    if findings is not None:
        # Pointer derefs (``*value``) then selector receivers (``value.``),
        # matching the legacy scan order.
        candidates = [*findings.pointer_deref_values, *findings.member_access_values]
    else:
        candidates = _go_nil_dereference_values_regex(expression)
    return _dedupe_strings(
        [
            _safe_identifier(value)
            for value in candidates
            if eligible_values is None or _safe_identifier(value) in eligible_values
        ]
    )


def _go_nil_dereference_values_regex(expression: str) -> list[str]:
    values: list[str] = []
    for match in re.finditer(r"\*\s*(?P<value>[A-Za-z_][A-Za-z0-9_]*)", expression):
        values.append(match.group("value"))
    for match in re.finditer(
        r"\b(?P<value>[A-Za-z_][A-Za-z0-9_]*)\s*\.",
        expression,
    ):
        values.append(match.group("value"))
    return values

def _z3_index_counterexample(
    index_name: str,
    length_name: str,
    known_index: int | None = None,
    is_unsigned: bool = False,
) -> dict[str, int] | None:
    """Counterexample for an unbounded index access, or ``None`` if provably safe.

    When ``known_index`` is given (a declared ``constant``/``immutable`` value),
    the index is pinned to that value so Z3 can't invent an impossible negative
    index (#296); the remaining, still-real concern is the upper bound
    (``index >= length``), so a shorter container is a genuine counterexample.

    For unsigned indices (``uint64`` etc.) the lower-bound concern is impossible,
    so only the upper bound is checked.
    """
    index = z3.Int(index_name)
    length = z3.Int(length_name)
    solver = z3.Solver()
    solver.add(length >= 0)
    if is_unsigned:
        solver.add(index >= 0, index >= length)
    else:
        solver.add(z3.Or(index < 0, index >= length))
    if known_index is not None:
        solver.add(index == known_index)
    if solver.check() == z3.sat:
        model = solver.model()
        return {
            index_name: model.eval(index, model_completion=True).as_long(),
            length_name: model.eval(length, model_completion=True).as_long(),
        }
    return None

def _z3_i64_overflow_counterexample(left_name: str, right_name: str) -> dict[str, int]:
    left = z3.Int(left_name)
    right = z3.Int(right_name)
    solver = z3.Solver()
    max_i64 = 9_223_372_036_854_775_807
    min_i64 = -9_223_372_036_854_775_808
    solver.add(left >= min_i64, left <= max_i64, right >= min_i64, right <= max_i64)
    solver.add(z3.Or(left + right > max_i64, left + right < min_i64))
    if solver.check() == z3.sat:
        model = solver.model()
        return {
            left_name: model.eval(left, model_completion=True).as_long(),
            right_name: model.eval(right, model_completion=True).as_long(),
        }
    return {left_name: max_i64, right_name: 1}

def _z3_solidity_overflow_counterexample(left_name: str, right_name: str) -> dict[str, int]:
    left = z3.Int(left_name)
    right = z3.Int(right_name)
    solver = z3.Solver()
    solver.add(
        left >= 0,
        left <= SOLIDITY_UINT256_MAX,
        right >= 0,
        right <= SOLIDITY_UINT256_MAX,
    )
    solver.add(left + right > SOLIDITY_UINT256_MAX)
    if solver.check() == z3.sat:
        model = solver.model()
        return {
            left_name: model.eval(left, model_completion=True).as_long(),
            right_name: model.eval(right, model_completion=True).as_long(),
        }
    return {left_name: SOLIDITY_UINT256_MAX, right_name: 1}

def _solidity_function_blocks(source: str) -> list[tuple[str, str]]:
    ts_blocks = tree_sitter_extract.function_blocks(source, "solidity", _safe_identifier)
    if ts_blocks is not None:
        return ts_blocks
    blocks: list[tuple[str, str]] = []
    for match in _SOLIDITY_FUNCTION_PATTERN.finditer(source):
        body = _balanced_brace_body(source, match.end() - 1)
        blocks.append((_safe_identifier(match.group("name")), body))
    return blocks

def _solidity_function_blocks_with_attrs(source: str) -> list[tuple[str, str, str]]:
    functions = tree_sitter_extract.extract_contract_functions(
        source, "solidity", _safe_identifier
    )
    if functions is not None:
        return [
            (fn.name, fn.attrs_text, fn.body)
            for fn in functions
            if fn.has_body
        ]
    # Regex fallback when tree-sitter / the grammar is unavailable.
    blocks: list[tuple[str, str, str]] = []
    for match in _SOLIDITY_FUNCTION_PATTERN.finditer(source):
        body = _balanced_brace_body(source, match.end() - 1)
        blocks.append(
            (
                _safe_identifier(match.group("name")),
                match.group("attrs") or "",
                body,
            )
        )
    return blocks

def _is_solidity_mock_source(source: str) -> bool:
    """Return True when every contract in the source is a mock contract.

    OpenZeppelin-style test mocks (``contracts/mocks/**``) are intentionally
    permissionless and may use save/call/restore patterns that look like
    reentrancy violations; treat them as test-only artifacts.
    """
    contract_names = re.findall(r"\b(?:abstract\s+)?contract\s+([A-Za-z_]\w*)", source)
    return bool(contract_names) and all("Mock" in name for name in contract_names)


def _detect_solidity_contract_issues(
    source: str, source_file: str | None = None
) -> list[ForeignSafetyIssue]:
    if source_file and ("/mocks/" in source_file or "\\mocks\\" in source_file):
        return []
    if _is_solidity_mock_source(source):
        return []
    issues: list[ForeignSafetyIssue] = []
    for name, attrs, body in _solidity_function_blocks_with_attrs(source):
        if _solidity_function_is_mutating_external(attrs, body):
            maybe_cei_issue = _solidity_cei_issue(name, attrs, body)
            if maybe_cei_issue is not None:
                issues.append(maybe_cei_issue)
            if _solidity_function_is_externally_callable(attrs) and not _solidity_function_has_access_guard(
                attrs,
                body,
            ):
                issues.append(
                    ForeignSafetyIssue(
                        function_name=name,
                        message=(
                            f"Solidity function `{name}` is an externally callable "
                            "state-mutating function with no access-control guard "
                            "(no `onlyOwner`-style modifier or `require(msg.sender == ...)`); "
                            "confirm this is intentionally permissionless"
                        ),
                    )
                )
    return issues

def _solidity_function_is_externally_callable(attrs: str) -> bool:
    return bool(re.search(r"\b(?:public|external)\b", attrs))

def _solidity_function_is_mutating_external(attrs: str, body: str) -> bool:
    return _solidity_function_has_storage_write(body) or _solidity_function_has_external_call(body)

def _solidity_function_has_external_call(body: str) -> bool:
    return any(pattern.search(body) for pattern in _SOLIDITY_EXTERNAL_CALL_PATTERNS)

def _solidity_function_has_storage_write(body: str) -> bool:
    return _solidity_first_storage_write(body) is not None

def _solidity_function_has_access_guard(attrs: str, body: str) -> bool:
    if _SOLIDITY_ACCESS_MODIFIER_PATTERN.search(attrs):
        return True
    return any(pattern.search(body) for pattern in _SOLIDITY_ACCESS_GUARD_PATTERNS)

def _solidity_named_return_params(attrs: str) -> set[str]:
    """Return the named return-parameter names declared in ``returns (...)``."""
    match = re.search(r"\breturns\s*\(([^)]*)\)", attrs)
    if not match:
        return set()
    return set(_solidity_params(match.group(1)).keys())


def _solidity_cei_issue(name: str, attrs: str, body: str) -> ForeignSafetyIssue | None:
    trace_result = _solidity_reentrancy_trace(name, attrs, body)
    if trace_result is None:
        return None
    guard_state, trace = trace_result
    return ForeignSafetyIssue(
        function_name=name,
        message=(
            f"Solidity function `{name}` may be vulnerable to reentrancy: "
            "verified guard-state-machine trace shows an external call reachable in "
            "the Unlocked state before a later state write "
            "(Checks-Effects-Interactions violation; move state updates before external "
            "calls or add a reentrancy guard)"
        ),
        counterexample={"reentrancy_trace": trace, "guard": guard_state},
    )

def _solidity_first_external_call(body: str) -> tuple[int, str] | None:
    matches: list[tuple[int, str]] = []
    for pattern in _SOLIDITY_EXTERNAL_CALL_PATTERNS:
        match = pattern.search(body)
        if match is not None:
            matches.append((match.start(), match.group(0)))
    if not matches:
        return None
    offset, snippet = min(matches, key=lambda item: item[0])
    return offset, _solidity_call_snippet(body, offset, snippet)

def _solidity_call_snippet(body: str, offset: int, fallback: str) -> str:
    statement_start = max(body.rfind(";", 0, offset), body.rfind("{", 0, offset))
    statement_start = max(statement_start, body.rfind("\n", 0, offset))
    tail = body[statement_start + 1 :] if statement_start != -1 else body[offset:]
    end_candidates = [
        candidate
        for candidate in (
            tail.find(";"),
            tail.find("\n"),
        )
        if candidate != -1
    ]
    if end_candidates:
        tail = tail[: min(end_candidates) + 1]
    tail = tail.strip()
    if len(tail) < len(fallback):
        return fallback
    return tail[:120]

def _solidity_ordered_op_trace(
    body: str, named_returns: set[str] | None = None
) -> list[_SolidityOpTraceItem]:
    ops: list[_SolidityOpTraceItem] = []
    named_returns = named_returns or set()
    for match in _SOLIDITY_OP_TRACE_PATTERN.finditer(body):
        if match.group("externalCall") is not None:
            offset = match.start("externalCall")
            snippet = _solidity_call_snippet(
                body,
                offset,
                match.group("externalCall").strip(),
            )
            ops.append(_SolidityOpTraceItem("externalCall", offset, snippet))
            continue
        if match.group("stateWrite") is not None:
            lhs = match.group("lhs") or ""
            if lhs in named_returns:
                # Assignments to named return parameters are local, not storage writes.
                continue
            statement_start = max(
                body.rfind(";", 0, match.start("stateWrite")),
                body.rfind("{", 0, match.start("stateWrite")),
            )
            statement_start = max(statement_start, body.rfind("\n", 0, match.start("stateWrite")))
            statement_prefix = body[statement_start + 1 : match.start("stateWrite")].strip()
            if _solidity_statement_is_local_declaration(statement_prefix) or statement_prefix.startswith("emit"):
                continue
            ops.append(_SolidityOpTraceItem("stateWrite", match.start("stateWrite"), lhs))
    return sorted(ops, key=lambda item: (item.offset, item.kind))

def _solidity_reentrancy_guard_present(attrs: str, body: str) -> bool:
    if _SOLIDITY_REENTRANCY_GUARD_MODIFIER_PATTERN.search(attrs):
        return True
    return _solidity_manual_lock_guard_present(body)

def _solidity_manual_lock_guard_present(body: str) -> bool:
    for pattern in _SOLIDITY_MANUAL_LOCK_REQUIRE_PATTERNS:
        for match in pattern.finditer(body):
            lock_var = match.group("var")
            if not lock_var:
                continue
            true_match = re.search(
                rf"\b{re.escape(lock_var)}\s*=\s*true\b",
                body,
                re.IGNORECASE,
            )
            false_match = re.search(
                rf"\b{re.escape(lock_var)}\s*=\s*false\b",
                body,
                re.IGNORECASE,
            )
            if true_match is None or false_match is None:
                continue
            if match.start() < true_match.start() < false_match.start():
                return True
    return False

def _solidity_reentrancy_trace(name: str, attrs: str, body: str) -> tuple[str, list[str]] | None:
    ops = _solidity_ordered_op_trace(body, named_returns=_solidity_named_return_params(attrs))
    if not any(op.kind == "externalCall" for op in ops):
        return None
    if not any(op.kind == "stateWrite" for op in ops):
        return None

    guarded = _solidity_reentrancy_guard_present(attrs, body)
    abstract_ops = [
        _SolidityOpTraceItem("lock", -1, "lock"),
        *ops,
        _SolidityOpTraceItem("unlock", len(body) + 1, "unlock"),
    ] if guarded else ops

    solver = z3.Solver()
    states = [z3.Int(f"{name}_guard_state_{index}") for index in range(len(abstract_ops) + 1)]
    solver.add(states[0] == _SOLIDITY_GUARD_UNLOCKED)
    for index, op in enumerate(abstract_ops):
        if op.kind == "lock":
            solver.add(states[index + 1] == _SOLIDITY_GUARD_LOCKED)
        elif op.kind == "unlock":
            solver.add(states[index + 1] == _SOLIDITY_GUARD_UNLOCKED)
        else:
            solver.add(states[index + 1] == states[index])

    ext_idx = z3.Int(f"{name}_external_call_index")
    write_idx = z3.Int(f"{name}_state_write_index")
    ext_positions = [index for index, op in enumerate(abstract_ops) if op.kind == "externalCall"]
    write_positions = [index for index, op in enumerate(abstract_ops) if op.kind == "stateWrite"]
    if not ext_positions or not write_positions:
        return None
    solver.add(z3.Or([ext_idx == index for index in ext_positions]))
    solver.add(z3.Or([write_idx == index for index in write_positions]))
    solver.add(ext_idx < write_idx)
    solver.add(
        z3.Or(
            [
                z3.And(ext_idx == index, states[index] == _SOLIDITY_GUARD_UNLOCKED)
                for index in ext_positions
            ]
        )
    )

    if solver.check() != z3.sat:
        return None

    model = solver.model()
    ext_value = model[ext_idx].as_long()
    write_value = model[write_idx].as_long()
    trace = [
        _solidity_format_trace_item(abstract_ops[ext_value]),
        _solidity_format_trace_item(abstract_ops[write_value]),
    ]
    return "absent", trace

def _solidity_format_trace_item(item: _SolidityOpTraceItem) -> str:
    return f"{item.kind}: {item.snippet}"


_SOLIDITY_GUARD_TRACE_TRANSLATOR_VERSION = "mumei-lean-translator-ir-v2"
_SOLIDITY_GUARD_TRACE_BRIDGE_LEMMA_HASH = "a3e9c1f4b7d2806e5f19347cab82d0963ef1a5bc70d4e8290f136d5ab7c84e11"


def extract_solidity_guard_trace_atoms(
    source: str,
    *,
    source_file: str | Path | None = None,
) -> list[dict[str, object]]:
    file_name = str(source_file or "<solidity-source>")
    atoms: list[dict[str, object]] = []
    for match in _SOLIDITY_FUNCTION_PATTERN.finditer(source):
        function_name = _safe_identifier(match.group("name"))
        attrs = match.group("attrs") or ""
        body = _balanced_brace_body(source, match.end() - 1)
        ordered_ops = [
            op.kind
            for op in _solidity_ordered_op_trace(body, named_returns=set())
            if op.kind == "externalCall"
        ]
        if not ordered_ops:
            continue
        guarded = _solidity_reentrancy_guard_present(attrs, body)
        guard_ops = (
            ["lock", *ordered_ops, "unlock"]
            if guarded
            else [*ordered_ops]
        )
        expected_outcome = "safe" if guarded else "none"
        line = _line_for_offset(source, match.start())
        atoms.append(
            _build_solidity_guard_trace_atom(
                function_name=function_name,
                source_file=file_name,
                line=line,
                guard_ops=guard_ops,
                expected_outcome=expected_outcome,
                guarded=guarded,
                body=body,
            )
        )
    return atoms


def build_solidity_guard_trace_proof_certificate(
    source: str,
    *,
    source_file: str | Path | None = None,
    package_name: str | None = None,
    package_version: str = "0",
    mumei_version: str = "test-fixture",
    z3_version: str | None = None,
    timestamp: str | None = None,
) -> dict[str, object]:
    file_name = str(source_file or "<solidity-source>")
    atoms = extract_solidity_guard_trace_atoms(source, source_file=file_name)
    return {
        "version": "1.0",
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "mumei_version": mumei_version,
        "z3_version": z3_version or f"Z3 version {z3.get_version_string()}",
        "file": file_name,
        "atoms": atoms,
        "package_name": package_name or Path(file_name).stem or "solidity",
        "package_version": package_version,
        "certificate_hash": _hash_guard_trace_payload(file_name, atoms),
        "all_verified": False,
    }


def _build_solidity_guard_trace_atom(
    *,
    function_name: str,
    source_file: str,
    line: int,
    guard_ops: list[str],
    expected_outcome: str,
    guarded: bool,
    body: str,
) -> dict[str, object]:
    safe_name = _safe_identifier(f"{function_name}_guard_trace")
    theorem_goal = _solidity_guard_trace_theorem_goal(guard_ops, expected_outcome)
    content_hash = _hash_guard_trace_payload(
        function_name,
        guard_ops,
        expected_outcome,
        source_file,
        body,
    )
    body_summary = (
        "guard trace proof for "
        f"{'a guarded external call' if guarded else 'an unguarded external call'}"
    )
    return {
        "name": safe_name,
        "z3_check_result": "unknown",
        "content_hash": content_hash,
        "status": "unknown",
        "proof_hash": _hash_guard_trace_payload("proof", content_hash, theorem_goal),
        "requires": "true",
        "ensures": "true",
        "body_expr": "",
        "body_summary": body_summary,
        "z3_result_class": "unknown",
        "escalation_reason": "sc",
        "logic_fragment_tag": "smart_contract_guard_trace",
        "logic_fragment_tags": ["smart_contract", "guard_trace"],
        "translator_version": _SOLIDITY_GUARD_TRACE_TRANSLATOR_VERSION,
        "binder_mapping": {},
        "bridge_lemma_hash": _SOLIDITY_GUARD_TRACE_BRIDGE_LEMMA_HASH,
        "translator_ir": {
            "sort": "contract_obligation",
            "binders": [],
            "theorem_goal": theorem_goal,
            "provenance_span": {
                "file": source_file,
                "line": line,
                "col": 1,
                "len": 0,
            },
            "lowering_rules": ["smart_contract_guard_trace_lowering"],
            "proof_trace_hints": [
                "use the concrete guard trace with SmartContract.runGuard",
            ],
            "requires_bridge_lemmas": [
                "MumeiLean.SmartContract.no_external_call_without_lock",
            ],
            "obligation_class": "smart_contract_guard_trace_obligation",
            "guard_trace": {
                "ops": guard_ops,
                "expected_outcome": expected_outcome,
            },
            "guard_trace_ops": guard_ops,
            "guard_trace_expected_outcome": expected_outcome,
        },
        "unknown_obligation_domain": "smart_contract",
    }


def _solidity_guard_trace_theorem_goal(guard_ops: list[str], expected_outcome: str) -> str:
    op_terms = ", ".join(f"GuardOp.{op}" for op in guard_ops)
    expected = "some GuardState.Unlocked" if expected_outcome == "safe" else "none"
    return f"runGuard GuardState.Unlocked [{op_terms}] = {expected}"


def _hash_guard_trace_payload(*parts: object) -> str:
    payload = json.dumps(parts, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

def _solidity_first_storage_write(
    body: str,
    minimum_offset: int = 0,
) -> tuple[str, int] | None:
    for match in _SOLIDITY_STORAGE_WRITE_PATTERN.finditer(body, minimum_offset):
        lhs = match.group("lhs")
        statement_start = max(body.rfind(";", 0, match.start()), body.rfind("{", 0, match.start()))
        statement_start = max(statement_start, body.rfind("\n", 0, match.start()))
        statement_prefix = body[statement_start + 1 : match.start()].strip()
        if _solidity_statement_is_local_declaration(statement_prefix):
            continue
        if statement_prefix.startswith("emit"):
            continue
        return lhs, match.start()
    return None

def _solidity_statement_is_local_declaration(statement_prefix: str) -> bool:
    if not statement_prefix:
        return False
    return bool(_SOLIDITY_LOCAL_DECLARATION_PATTERN.match(statement_prefix))

def _rust_function_blocks(source: str) -> list[tuple[str, str]]:
    ts_blocks = tree_sitter_extract.function_blocks(source, "rust", _safe_identifier)
    if ts_blocks is not None:
        return ts_blocks
    # Regex fallback: strip literals/comments first so ``fn``/braces inside
    # strings or comments do not confuse the pattern (the tree-sitter path
    # handles this natively).
    stripped = _strip_go_rust_literals_and_comments(source)
    pattern = re.compile(
        r"(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+"
        r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?:<[^>]+>)?\s*"
        r"\((?P<params>[^)]*)\)\s*(?:->\s*(?P<ret>[^{;\n]+))?\s*\{",
        re.DOTALL,
    )
    blocks: list[tuple[str, str]] = []
    for match in pattern.finditer(stripped):
        body = _balanced_brace_body(stripped, match.end() - 1)
        blocks.append((_safe_identifier(match.group("name")), body))
    return blocks

def _rust_const_array_lengths(source: str) -> dict[str, int]:
    """Map Rust ``const``/``static`` array names to their element count."""
    lengths: dict[str, int] = {}
    pattern = re.compile(
        r"\b(?:const|static(?:\s+mut)?)\s+"
        r"(?P<name>[A-Za-z_]\w*)\s*:\s*\[[^;\]]*;\s*(?P<len>\d+)\s*\]",
    )
    for match in pattern.finditer(source):
        try:
            lengths[match.group("name")] = int(match.group("len"))
        except ValueError:
            continue
    return lengths


def _rust_local_usize_cast_offsets(body: str) -> dict[str, tuple[str, int]]:
    """Map local variable names to ``(param - offset) as usize`` initializers."""
    casts: dict[str, tuple[str, int]] = {}
    pattern = re.compile(
        r"\blet\s+(?:mut\s+)?(?P<name>[A-Za-z_]\w*)\s*=\s*"
        r"\(\s*(?P<param>[A-Za-z_]\w*)\s*-\s*(?P<offset>\d+)\s*\)\s*as\s+usize\s*;"
    )
    for match in pattern.finditer(body):
        casts[match.group("name")] = (match.group("param"), int(match.group("offset")))
    return casts


def _is_rust_usize_cast_array_issue(
    issue: ForeignSafetyIssue,
    source: str,
    blocks: list[tuple[str, str]],
) -> bool:
    """Suppress index-bounds false positives for ``(param - N) as usize`` into const arrays.

    The cast from a signed parameter to ``usize`` is common for 1-indexed
    constant lookup tables (e.g. ``LAST_DAYS[(month - 1) as usize]``).
    Without range information the tool cannot prove safety, so treat it as a
    caller-contract false positive rather than a spurious refutation.
    """
    match = re.search(r"`([A-Za-z_]\w*)\[([A-Za-z_]\w*)\]`", issue.message)
    if not match:
        return False
    container, index = match.groups()
    const_lengths = _rust_const_array_lengths(source)
    if container not in const_lengths:
        return False
    bodies = {name: body for name, body in blocks}
    body = bodies.get(issue.function_name, "")
    return index in _rust_local_usize_cast_offsets(body)


def _go_function_blocks(source: str) -> list[tuple[str, str]]:
    ts_blocks = tree_sitter_extract.function_blocks(source, "go", _safe_identifier)
    if ts_blocks is not None:
        return ts_blocks
    pattern = re.compile(
        r"func\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*"
        r"\((?P<params>[^)]*)\)\s*(?P<ret>[\*\[\]A-Za-z0-9_]+)?\s*\{",
        re.DOTALL,
    )
    blocks: list[tuple[str, str]] = []
    for match in pattern.finditer(source):
        body = _balanced_brace_body(source, match.end() - 1)
        blocks.append((_safe_identifier(match.group("name")), body))
    return blocks

def _balanced_brace_body(source: str, opening_brace: int) -> str:
    depth = 0
    for index in range(opening_brace, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[opening_brace + 1 : index]
    return source[opening_brace + 1 :]

def _typescript_function_blocks(source: str) -> list[tuple[str, str]]:
    ts_blocks = tree_sitter_extract.function_blocks(source, "typescript", _safe_identifier)
    if ts_blocks is not None:
        return ts_blocks
    blocks: list[tuple[str, str]] = []
    function_pattern = re.compile(
        r"(?:export\s+)?(?:async\s+)?function\s+"
        r"(?P<name>[A-Za-z_$][\w$]*)\s*(?:<[^>]+>)?\s*"
        r"\((?P<params>[^)]*)\)\s*(?::\s*(?P<ret>[^{=\n]+))?\s*"
        r"\{(?P<body>.*?)\}",
        re.DOTALL,
    )
    arrow_pattern = re.compile(
        r"(?:export\s+)?(?:const|let)\s+"
        r"(?P<name>[A-Za-z_$][\w$]*)\s*=\s*"
        r"(?:async\s*)?\((?P<params>[^)]*)\)\s*"
        r"(?::\s*(?P<ret>[^=]+?))?\s*=>\s*(?P<body>\{.*?\}|[^;\n]+)",
        re.DOTALL,
    )
    blocks.extend(
        (_safe_identifier(match.group("name")), match.group("body"))
        for match in function_pattern.finditer(source)
    )
    blocks.extend(
        (_safe_identifier(match.group("name")), match.group("body"))
        for match in arrow_pattern.finditer(source)
    )
    return blocks


def _ts_nullable_param_set(params_text: str) -> set[str]:
    """Return the set of parameter names that may be null/undefined."""
    nullable: set[str] = set()
    for raw in _split_params(params_text):
        if not raw.strip():
            continue
        parts = raw.split(":", 1)
        pname = parts[0].strip().split("=")[0].strip().rstrip("?")
        if not pname:
            continue
        if len(parts) < 2:
            # No type annotation: conservative.
            nullable.add(_safe_identifier(pname))
            continue
        type_text = parts[1].strip()
        is_optional = raw.strip().startswith(pname + "?") or type_text.endswith("?")
        if (
            is_optional
            or "null" in type_text.lower()
            or "undefined" in type_text.lower()
            or type_text.lower() == "any"
        ):
            nullable.add(_safe_identifier(pname))
    return nullable


def _typescript_nullable_param_names(source: str) -> dict[str, set[str]]:
    """Map each TypeScript function name to the set of possibly-null parameter names.

    A parameter is treated as nullable when it has no type annotation, is
    optional, or its type contains ``null``/``undefined``/``any``.  Non-null
    array/object parameters are excluded so that ``.length`` and indexing do not
    produce false positives for well-typed inputs.
    """
    extracted = tree_sitter_extract.extract_functions(source, "typescript", _safe_identifier)
    if extracted is not None:
        return {
            fn.name: _ts_nullable_param_set(fn.params_text or "")
            for fn in extracted
            if fn.has_body
        }
    # Fallback regex when tree-sitter is unavailable.
    result: dict[str, set[str]] = {}
    function_pattern = re.compile(
        r"(?:export\s+)?(?:async\s+)?function\s+"
        r"(?P<name>[A-Za-z_$][\w$]*)\s*(?:<[^>]+>)?\s*"
        r"\((?P<params>[^)]*)\)\s*(?::\s*(?P<ret>[^{=\n]+))?\s*\{",
        re.DOTALL,
    )
    arrow_pattern = re.compile(
        r"(?:export\s+)?(?:const|let)\s+"
        r"(?P<name>[A-Za-z_$][\w$]*)\s*(?::\s*(?P<vartype>[^=]+?))?\s*=\s*"
        r"(?:async\s*)?\((?P<params>[^)]*)\)\s*"
        r"(?::\s*(?P<ret>[^=]+?))?\s*=>\s*(?:\{.*?\}|[^;\n]+)",
        re.DOTALL,
    )
    for match in (*function_pattern.finditer(source), *arrow_pattern.finditer(source)):
        name = _safe_identifier(match.group("name"))
        params_text = match.group("params") or ""
        result[name] = _ts_nullable_param_set(params_text)
    return result


def _ts_typeof_guarded_values(expression: str) -> set[str]:
    """Return identifiers narrowed to non-null by type or truthiness guards.

    TypeScript's ``typeof`` type guard makes subsequent ``.length`` / member
    access safe in the same ``&&`` chain.  A guard of the form
    ``typeof x === 'string' && x.length`` means ``x`` is a string on the right.
    The same applies to a truthiness guard ``x && x.length`` and to
    ``Array.isArray(x) && x.length``.
    """
    guarded: set[str] = set()
    # Match ``typeof x === 'string'`` followed (possibly through a closing paren)
    # by ``&&``.  Also accept ``number`` for numeric member accesses.
    for match in re.finditer(
        r"typeof\s+([A-Za-z_$][\w$]*)\s*===\s*['\"](?:string|number)['\"]\s*\)?\s*&&",
        expression,
    ):
        guarded.add(match.group(1))
    # Truthiness guard ``message && message.length > 500``
    for match in re.finditer(
        r"\b([A-Za-z_$][\w$]*)\s*&&\s*\1\.(?:length|len|is_empty)\b",
        expression,
    ):
        guarded.add(match.group(1))
    # ``Array.isArray(x) && ...`` narrows ``x`` to an array object.
    for match in re.finditer(
        r"Array\.isArray\s*\(\s*([A-Za-z_$][\w$]*)\s*\)\s*\)?\s*&&",
        expression,
    ):
        guarded.add(match.group(1))
    return guarded


def _return_expressions(body: str, fallback: bool = True, language: str = "") -> list[str]:
    """Return the expressions of all ``return`` statements in ``body``.

    Balances parentheses, brackets, braces and ternary ``?:`` pairs so
    multi-line returns are captured in full.
    """
    body = _mask_nested_function_literals(body, language)
    stripped = _strip_go_rust_literals_and_comments(body)
    expressions: list[str] = []
    for match in re.finditer(r"\breturn\b", stripped):
        end = match.end()
        if end < len(stripped) and (stripped[end].isalnum() or stripped[end] == "_"):
            continue
        expr = _extract_return_expression(stripped, body, end)
        if expr:
            expressions.append(expr)
    # For expression-bodied arrow functions with no ``return`` keyword.
    if not expressions and fallback:
        body_stripped = body.strip()
        if body_stripped and "\n" not in body_stripped:
            expressions.append(body_stripped.rstrip(";"))
    return expressions

def _last_rust_expression(body: str) -> str:
    lines = [line.strip().rstrip(";") for line in body.strip().splitlines() if line.strip()]
    return lines[-1] if lines else ""
