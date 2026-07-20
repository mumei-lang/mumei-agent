"""Foreign-code contract inference helpers for foreign code strategy."""
from __future__ import annotations

import ast
from datetime import datetime, timezone
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
            target.append(_strip_contract_marker(line, marker))
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

def _safe_identifier(value: str) -> str:
    safe = re.sub(r"\W+", "_", value.strip())
    safe = safe.strip("_")
    if not safe:
        return "foreign_code_atom"
    if safe[0].isdigit():
        return f"atom_{safe}"
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


def _detect_safety_issues(source: str, language: str) -> list[ForeignSafetyIssue]:
    if _is_generated_source(source):
        return []
    normalized = _normalize_language(language)
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
        stripped_source = _strip_go_rust_literals_and_comments(source)
        return _detect_go_safety_issues(stripped_source)
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
        )
        issues.extend(_detect_solidity_contract_issues(source))
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


def _solidity_declared_constants(source: str) -> dict[str, int]:
    """Map Solidity ``constant``/``immutable`` names to their integer literal.

    Thin wrapper over the shared cross-language constant model so the
    divide-by-zero and out-of-bounds heuristics don't model a named constant
    (e.g. curve order ``N``, radix ``EVM_TREE_RADIX``) as a free Z3 integer that
    can be picked as ``0`` / ``-1`` (#296).
    """
    return semantic_safety.collect_declared_constants(source, "solidity")

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
) -> list[ForeignSafetyIssue]:
    issues: list[ForeignSafetyIssue] = []
    fallback = label == "TypeScript"
    language = label.lower()
    for name, body in blocks:
        expressions = _return_expressions(body, fallback=fallback, language=language)
        if not expressions and label == "Rust":
            expressions = [_last_rust_expression(body)]
        dereference_values = None
        if label == "TypeScript" and nullable_params is not None:
            dereference_values = nullable_params.get(name)
        for expression in expressions:
            issues.extend(
                _issues_for_expression(
                    name,
                    expression,
                    label,
                    dereference_values=dereference_values,
                    known_constants=known_constants,
                    mapping_names=mapping_names,
                )
            )
    return issues

_GO_BUILTIN_TYPES = {
    "string", "int", "int8", "int16", "int32", "int64",
    "uint", "uint8", "uint16", "uint32", "uint64", "uintptr",
    "float32", "float64", "complex64", "complex128",
    "bool", "byte", "rune", "error", "any", "comparable",
}


def _go_package_name(source: str) -> str:
    """Return the Go package clause from ``source`` (without a path)."""
    match = re.search(r"^\s*package\s+([A-Za-z_]\w*)", source, re.MULTILINE)
    return match.group(1) if match else ""


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
    if pkg == "web" and re.search(r"\btype\s+Context\s+struct\b", source):
        # Web framework request contexts (e.g. Grafana ``pkg/web``) are always
        # created from an active HTTP request; nil receiver counterexamples on
        # their methods are false positives.
        contracts.add("Context")
    return contracts


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
    return False


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


def _go_method_receiver_name(params_text: str) -> str | None:
    """Return the receiver variable name, or None if not a method."""
    if _go_method_receiver_type(params_text) is None:
        return None
    params_text = params_text.strip()
    if not params_text:
        return None
    first = params_text.split(",", 1)[0].strip()
    match = re.match(r"([A-Za-z_]\w*)\s+", first)
    return match.group(1) if match else None


def _go_method_receiver_type(params_text: str) -> str | None:
    """Return the receiver type of a Go method, or None for a standalone function."""
    params_text = params_text.strip()
    if not params_text:
        return None
    # The first parameter in a method declaration is the receiver.
    first = params_text.split(",", 1)[0].strip()
    # Split the first parameter into name and type.  Receivers are either a
    # named type ``T`` or a pointer ``*T``; built-in scalar parameters such as
    # ``s string`` are ordinary function arguments, not receivers.
    match = re.fullmatch(r"[A-Za-z_]\w*\s+(\*?\s*[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_]\w*)?)\.?", first)
    if not match:
        return None
    rtype = match.group(1).replace(" ", "")
    base = rtype.lstrip("*")
    if base in _GO_BUILTIN_TYPES:
        return None
    return rtype


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


def _detect_go_safety_issues(source: str) -> list[ForeignSafetyIssue]:
    issues: list[ForeignSafetyIssue] = []
    functions = tree_sitter_extract.extract_contract_functions(
        source, "go", _safe_identifier
    )
    if functions is not None:
        flag_value_types = _go_flag_value_receiver_types(functions)
        caller_contract_types = _go_caller_contract_receiver_types(source)
        callback_names = _go_callback_function_names(source, functions)
        for fn in functions:
            if not fn.has_body or _is_go_test_name(fn.raw_name or fn.name):
                continue
            body = fn.body
            param_names = _go_nillable_param_names(fn.params_text)
            param_types = _go_param_types(fn.params_text)
            local_names = _local_variable_names(body, "go")
            expressions = _return_expressions(body, fallback=False, language="go")
            guarded = _go_nil_guarded_return_values(body)
            rtype = _go_method_receiver_type(fn.params_text)
            receiver_name = _go_method_receiver_name(fn.params_text)
            suppress_nil = (
                fn.name in {"String", "Get"}
                and rtype is not None
                and rtype in flag_value_types
            )
            is_method = source[fn.start_char : fn.body_start_char].lstrip().startswith("func (")
            suppress_receiver_nil = (
                rtype is not None
                and (
                    rtype.lstrip("*") in caller_contract_types
                    or _go_is_known_interface_method(fn.name, fn.params_text, fn.return_type)
                )
            )
            first_param = _go_first_param_name(fn.params_text)
            suppress_callback_nil = not is_method and fn.name in callback_names and first_param is not None
            for index, expression in enumerate(expressions):
                expr_issues = _issues_for_expression(
                    fn.name,
                    expression,
                    "Go",
                    dereference_values=param_names,
                    local_names=local_names,
                    param_types=param_types,
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
    caller_contract_types = _go_caller_contract_receiver_types(source)
    # Regex fallback cannot reliably distinguish methods from top-level
    # functions, so callback suppression is skipped in that path.
    for name, params_text, _return_type, body in go_decls:
        param_names = _go_nillable_param_names(params_text)
        param_types = _go_param_types(params_text)
        local_names = _local_variable_names(body, "go")
        expressions = _return_expressions(body, fallback=False, language="go")
        guarded = _go_nil_guarded_return_values(body)
        rtype = _go_method_receiver_type(params_text)
        receiver_name = _go_method_receiver_name(params_text)
        suppress_nil = (
            name in {"String", "Get"}
            and rtype is not None
            and rtype in flag_value_types
        )
        suppress_receiver_nil = (
            rtype is not None
            and (
                rtype.lstrip("*") in caller_contract_types
                or _go_is_known_interface_method(name, params_text, _return_type)
            )
        )
        for index, expression in enumerate(expressions):
            expr_issues = _issues_for_expression(
                _safe_identifier(name),
                expression,
                "Go",
                dereference_values=param_names,
                local_names=local_names,
                param_types=param_types,
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
) -> ForeignSafetyIssue | None:
    # A declared `constant`/`immutable` index (e.g. `decoded[EVM_TREE_RADIX]`,
    # EVM_TREE_RADIX=16) is pinned to its value so Z3 can't invent an
    # impossible negative index (#296). The upper bound is still a real
    # concern, so we keep checking `index < len` rather than skipping it.
    if label == "Go" and param_types:
        container_type = param_types.get(container, "")
        if container_type.startswith("map["):
            # Map key access is always safe (returns zero value if missing).
            return None
    if mapping_names and container in mapping_names:
        # Solidity mapping key access is always safe.
        return None
    known_index = known_constants.get(index)
    if known_index is not None and known_index < 0:
        known_index = None
    counterexample = _z3_index_counterexample(
        index, f"len_{container}", known_index=known_index
    )
    if counterexample is None:
        return None
    required_contracts = (
        (f"{index} < len_{container}",)
        if known_index is not None
        else (f"{index} >= 0", f"{index} < len_{container}")
    )
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


def _division_safety_issue(
    function_name: str,
    divisor: str,
    label: str,
    known_constants: dict[str, int],
    guaranteed_nonzero: set[str] | None = None,
) -> ForeignSafetyIssue | None:
    # A non-zero `constant`/`immutable` divisor (e.g. `x % N` where N is the
    # secp256r1 curve order) can never be zero, so don't emit a bogus
    # divide-by-zero from modeling it as a free integer (#296).
    if known_constants.get(divisor, 0) != 0:
        return None
    if guaranteed_nonzero and divisor in guaranteed_nonzero:
        return None
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


def _i64_overflow_safety_issue(
    function_name: str,
    left: str,
    right: str,
    label: str,
    expression: str = "",
    local_names: set[str] | None = None,
) -> ForeignSafetyIssue | None:
    if _is_pointer_arithmetic_expression(expression, left, right):
        return None
    if local_names and (left in local_names or right in local_names):
        # Arithmetic over local loop variables cannot be expressed as a
        # precondition on the atom's parameters, so treat it as trusted.
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
) -> list[ForeignSafetyIssue]:
    known_constants = known_constants or {}
    guaranteed_nonzero = _guaranteed_nonzero_in_expression(expression)
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
            issue = _index_safety_issue(
                function_name, container, index, label, known_constants, param_types=param_types, mapping_names=mapping_names
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
        for match in re.finditer(
            r"\b(?P<value>[A-Za-z_][A-Za-z0-9_]*)!?\.(?:length|len|is_empty)\b",
            expression,
        ):
            value = match.group("value")
            if dereference_values is not None and value not in dereference_values:
                continue
            issues.append(_null_safety_issue(function_name, value, label))
    if label not in {"TypeScript", "JavaScript"}:
        for match in re.finditer(
            r"\b(?P<left>[A-Za-z_][A-Za-z0-9_]*)\s*(?P<op>/|%)\s*(?P<right>[A-Za-z_][A-Za-z0-9_]*)",
            expression,
        ):
            issue = _division_safety_issue(
                function_name, match.group("right"), label, known_constants, guaranteed_nonzero
            )
            if issue is not None:
                issues.append(issue)
    if label in {"Go", "Rust"}:
        for left, right in _addition_pairs_regex(expression):
            issue = _i64_overflow_safety_issue(
                function_name, left, right, label, expression, local_names=local_names
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
    param_types: dict[str, str] | None = None,
    mapping_names: set[str] | None = None,
) -> list[ForeignSafetyIssue]:
    """Build safety issues from syntax-tree findings.

    Emits issues in the same category order as the regex path (index, then
    nil/null, then division, then overflow) and reuses the shared issue
    builders so messages, counterexamples and required contracts are identical.
    """
    issues: list[ForeignSafetyIssue] = []
    if label not in {"TypeScript", "JavaScript"}:
        for container, index in findings.index_accesses:
            issue = _index_safety_issue(function_name, container, index, label, known_constants, param_types=param_types, mapping_names=mapping_names)
            if issue is not None:
                issues.append(issue)
    if label == "Go":
        for value in _go_nil_dereference_values(expression, dereference_values):
            issues.append(_go_nil_safety_issue(function_name, value, label))
    elif label == "TypeScript":
        for value in findings.length_access_values:
            if dereference_values is not None and value not in dereference_values:
                continue
            issues.append(_null_safety_issue(function_name, value, label))
    if label not in {"TypeScript", "JavaScript"}:
        for divisor in findings.divisors:
            issue = _division_safety_issue(
                function_name, divisor, label, known_constants, guaranteed_nonzero
            )
            if issue is not None:
                issues.append(issue)
    if label in {"Go", "Rust"}:
        for left, right in findings.additions:
            issue = _i64_overflow_safety_issue(
                function_name, left, right, label, expression, local_names=local_names
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
            value
            for value in candidates
            if eligible_values is None or value in eligible_values
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
) -> dict[str, int] | None:
    """Counterexample for an unbounded index access, or ``None`` if provably safe.

    When ``known_index`` is given (a declared ``constant``/``immutable`` value),
    the index is pinned to that value so Z3 can't invent an impossible negative
    index (#296); the remaining, still-real concern is the upper bound
    (``index >= length``), so a shorter container is a genuine counterexample.
    """
    index = z3.Int(index_name)
    length = z3.Int(length_name)
    solver = z3.Solver()
    solver.add(length >= 0, z3.Or(index < 0, index >= length))
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

def _detect_solidity_contract_issues(source: str) -> list[ForeignSafetyIssue]:
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

def _solidity_ordered_op_trace(body: str) -> list[_SolidityOpTraceItem]:
    ops: list[_SolidityOpTraceItem] = []
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
    ops = _solidity_ordered_op_trace(body)
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
            for op in _solidity_ordered_op_trace(body)
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


def _typescript_nullable_param_names(source: str) -> dict[str, set[str]]:
    """Map each TypeScript function name to the set of possibly-null parameter names.

    A parameter is treated as nullable when it has no type annotation, is
    optional, or its type contains ``null``/``undefined``/``any``.  Non-null
    array/object parameters are excluded so that ``.length`` and indexing do not
    produce false positives for well-typed inputs.
    """
    result: dict[str, set[str]] = {}
    function_pattern = re.compile(
        r"(?:export\s+)?(?:async\s+)?function\s+"
        r"(?P<name>[A-Za-z_$][\w$]*)\s*(?:<[^>]+>)?\s*"
        r"\((?P<params>[^)]*)\)\s*(?::\s*(?P<ret>[^{=\n]+))?\s*\{",
        re.DOTALL,
    )
    arrow_pattern = re.compile(
        r"(?:export\s+)?(?:const|let)\s+"
        r"(?P<name>[A-Za-z_$][\w$]*)\s*=\s*"
        r"(?:async\s*)?\((?P<params>[^)]*)\)\s*"
        r"(?::\s*(?P<ret>[^=]+?))?\s*=>\s*(?:\{.*?\}|[^;\n]+)",
        re.DOTALL,
    )
    for match in (*function_pattern.finditer(source), *arrow_pattern.finditer(source)):
        name = _safe_identifier(match.group("name"))
        nullable: set[str] = set()
        params_text = match.group("params")
        if params_text:
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
        result[name] = nullable
    return result


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
