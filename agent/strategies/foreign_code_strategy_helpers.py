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

from agent.cross_validation_foreign import (
    SOLIDITY_UINT256_MAX,
    _dedupe_strings,
    _go_function_declarations,
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

def to_mumei_atom(spec: ForeignCodeSpec) -> str:
    """Convert a foreign-code contract into Mumei atom syntax."""
    params = ", ".join(
        f"{_safe_identifier(name)}: {_mumei_type(type_name)}"
        for name, type_name in spec.params.items()
    )
    return_type = _mumei_type(spec.return_type)
    requires = _join_contracts(spec.preconditions)
    ensures = _join_contracts(spec.postconditions)
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

def _split_params(params_text: str) -> list[str]:
    params: list[str] = []
    current: list[str] = []
    depth = 0
    for char in params_text:
        if char in "([{<":
            depth += 1
        elif char in ")]}>":
            depth = max(0, depth - 1)
        if char == "," and depth == 0:
            params.append("".join(current))
            current = []
        else:
            current.append(char)
    if current:
        params.append("".join(current))
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

def _mumei_type(type_name: str) -> str:
    normalized = _python_type_name(type_name).strip()
    normalized = normalized.removeprefix("Promise<").removesuffix(">")
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
    if normalized == "bool":
        return "true"
    if normalized == "string":
        return '""'
    if normalized == "f64":
        return "0.0"
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

def _detect_safety_issues(source: str, language: str) -> list[ForeignSafetyIssue]:
    normalized = _normalize_language(language)
    if normalized == "rust":
        stripped_source = _strip_go_rust_literals_and_comments(source)
        return _detect_block_safety_issues(
            stripped_source,
            _rust_function_blocks(stripped_source),
            "Rust",
        )
    if normalized == "typescript":
        return _detect_block_safety_issues(
            source,
            _typescript_function_blocks(source),
            "TypeScript",
        )
    if normalized == "go":
        stripped_source = _strip_go_rust_literals_and_comments(source)
        return _detect_go_safety_issues(stripped_source)
    if normalized == "python":
        return _detect_python_safety_issues(source)
    if normalized == "solidity":
        issues = _detect_block_safety_issues(
            source,
            _solidity_function_blocks(source),
            "Solidity",
        )
        issues.extend(_detect_solidity_contract_issues(source))
        return issues
    return []

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
) -> list[ForeignSafetyIssue]:
    issues: list[ForeignSafetyIssue] = []
    for name, body in blocks:
        if label in {"Go", "Rust"}:
            body = _strip_go_rust_literals_and_comments(body)
        expressions = _return_expressions(body)
        if not expressions and label == "Rust":
            expressions = [_last_rust_expression(body)]
        for expression in expressions:
            issues.extend(_issues_for_expression(name, expression, label))
    return issues

def _detect_go_safety_issues(source: str) -> list[ForeignSafetyIssue]:
    issues: list[ForeignSafetyIssue] = []
    for name, params_text, _return_type, body in _go_function_declarations(source):
        body = _strip_go_rust_literals_and_comments(body)
        param_names = set(_go_params(params_text))
        for expression in _return_expressions(body):
            issues.extend(
                _issues_for_expression(
                    _safe_identifier(name),
                    expression,
                    "Go",
                    dereference_values=param_names,
                )
            )
    return issues

def _operand_is_member_or_call(expression: str, span: tuple[int, int]) -> bool:
    """True when the identifier at ``span`` is a member access or call receiver.

    ``result + SafeCast.toUint(...)`` must not treat ``SafeCast`` as an integer
    addend: it is a library/method-call receiver, not a variable. Modeling it as
    a free ``uint256`` yields bogus overflow counterexamples (#281).
    """
    start, end = span
    after = expression[end:].lstrip()
    if after[:1] in {".", "("}:
        return True
    before = expression[:start].rstrip()
    return before[-1:] == "."


def _issues_for_expression(
    function_name: str,
    expression: str,
    label: str,
    *,
    dereference_values: set[str] | None = None,
) -> list[ForeignSafetyIssue]:
    if label in {"Go", "Rust"}:
        expression = _strip_go_rust_literals_and_comments(expression)
    issues: list[ForeignSafetyIssue] = []
    for match in re.finditer(
        r"\b(?P<container>[A-Za-z_][A-Za-z0-9_]*)\s*\[\s*(?P<index>[A-Za-z_][A-Za-z0-9_]*)\s*\]",
        expression,
    ):
        container = match.group("container")
        index = match.group("index")
        counterexample = _z3_index_counterexample(index, f"len_{container}")
        issues.append(
            ForeignSafetyIssue(
                function_name=function_name,
                message=(
                    f"{label} function `{function_name}` can index `{container}[{index}]` "
                    f"without a bounds contract (Z3 counterexample: "
                    + ", ".join(f"{key}={value}" for key, value in counterexample.items())
                    + ")"
                ),
                required_contracts=(
                    f"{index} >= 0",
                    f"{index} < len_{container}",
                ),
                counterexample=counterexample,
            )
        )
    if label == "Go":
        for value in _go_nil_dereference_values(expression, dereference_values):
            counterexample = {f"{value}_is_nil": True}
            issues.append(
                ForeignSafetyIssue(
                    function_name=function_name,
                    message=(
                        f"{label} function `{function_name}` can dereference `{value}` "
                        "without a non-nil contract "
                        f"(Z3 counterexample: {value}_is_nil=true)"
                    ),
                    required_contracts=(f"{value} != nil",),
                    counterexample=counterexample,
                )
            )
    else:
        for match in re.finditer(
            r"\b(?P<value>[A-Za-z_][A-Za-z0-9_]*)!?\.(?:length|len|is_empty)\b",
            expression,
        ):
            value = match.group("value")
            counterexample = {f"{value}_is_null": True}
            issues.append(
                ForeignSafetyIssue(
                    function_name=function_name,
                    message=(
                        f"{label} function `{function_name}` can dereference `{value}` "
                        "without a non-null contract "
                        f"(Z3 counterexample: {value}_is_null=true)"
                    ),
                    required_contracts=(
                        f"{value} != null",
                        f"{value} != undefined",
                    ),
                    counterexample=counterexample,
                )
            )
    for match in re.finditer(
        r"\b(?P<left>[A-Za-z_][A-Za-z0-9_]*)\s*(?P<op>/|%)\s*(?P<right>[A-Za-z_][A-Za-z0-9_]*)",
        expression,
    ):
        divisor = match.group("right")
        counterexample = {divisor: 0}
        issues.append(
            ForeignSafetyIssue(
                function_name=function_name,
                message=(
                    f"{label} function `{function_name}` can divide by `{divisor}` "
                    f"without a non-zero contract (Z3 counterexample: {divisor}=0)"
                ),
                required_contracts=(f"{divisor} != 0",),
                counterexample=counterexample,
            )
        )
    if label in {"Go", "Rust"}:
        for match in re.finditer(
            r"\b(?P<left>[A-Za-z_][A-Za-z0-9_]*)\s*\+\s*(?P<right>[A-Za-z_][A-Za-z0-9_]*)",
            expression,
        ):
            if _operand_is_member_or_call(
                expression, match.span("left")
            ) or _operand_is_member_or_call(expression, match.span("right")):
                continue
            left = match.group("left")
            right = match.group("right")
            counterexample = _z3_i64_overflow_counterexample(left, right)
            issues.append(
                ForeignSafetyIssue(
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
            )
    if label == "Solidity":
        for match in re.finditer(
            r"\b(?P<left>[A-Za-z_][A-Za-z0-9_]*)\s*\+\s*(?P<right>[A-Za-z_][A-Za-z0-9_]*)",
            expression,
        ):
            if _operand_is_member_or_call(
                expression, match.span("left")
            ) or _operand_is_member_or_call(expression, match.span("right")):
                continue
            left = match.group("left")
            right = match.group("right")
            counterexample = _z3_solidity_overflow_counterexample(left, right)
            issues.append(
                ForeignSafetyIssue(
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
            )
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
    values: list[str] = []
    for match in re.finditer(r"\*\s*(?P<value>[A-Za-z_][A-Za-z0-9_]*)", expression):
        value = match.group("value")
        if eligible_values is None or value in eligible_values:
            values.append(value)
    for match in re.finditer(
        r"\b(?P<value>[A-Za-z_][A-Za-z0-9_]*)\s*\.",
        expression,
    ):
        value = match.group("value")
        if eligible_values is None or value in eligible_values:
            values.append(value)
    return _dedupe_strings(values)

def _z3_index_counterexample(index_name: str, length_name: str) -> dict[str, int]:
    index = z3.Int(index_name)
    length = z3.Int(length_name)
    solver = z3.Solver()
    solver.add(length >= 0, z3.Or(index < 0, index >= length))
    if solver.check() == z3.sat:
        model = solver.model()
        return {
            index_name: model.eval(index, model_completion=True).as_long(),
            length_name: model.eval(length, model_completion=True).as_long(),
        }
    return {index_name: 0, length_name: 0}

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
    blocks: list[tuple[str, str]] = []
    for match in _SOLIDITY_FUNCTION_PATTERN.finditer(source):
        body = _balanced_brace_body(source, match.end() - 1)
        blocks.append((_safe_identifier(match.group("name")), body))
    return blocks

def _solidity_function_blocks_with_attrs(source: str) -> list[tuple[str, str, str]]:
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
    pattern = re.compile(
        r"(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+"
        r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?:<[^>]+>)?\s*"
        r"\((?P<params>[^)]*)\)\s*(?:->\s*(?P<ret>[^{;\n]+))?\s*\{(?P<body>.*?)\}",
        re.DOTALL,
    )
    return [(_safe_identifier(match.group("name")), match.group("body")) for match in pattern.finditer(source)]

def _go_function_blocks(source: str) -> list[tuple[str, str]]:
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

def _return_expressions(body: str) -> list[str]:
    stripped = body.strip()
    if stripped.startswith("{"):
        stripped = stripped[1:-1]
    expressions = [match.group(1).strip() for match in re.finditer(r"\breturn\s+([^;\n}]+)", stripped)]
    if not expressions and stripped and "\n" not in stripped:
        expressions.append(stripped.rstrip(";"))
    return expressions

def _last_rust_expression(body: str) -> str:
    lines = [line.strip().rstrip(";") for line in body.strip().splitlines() if line.strip()]
    return lines[-1] if lines else ""
