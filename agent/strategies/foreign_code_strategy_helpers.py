"""Foreign-code contract inference helpers for foreign code strategy."""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
import re
from typing import Iterable

import z3

from agent.cross_validation_foreign import (
    SOLIDITY_UINT256_MAX,
    _dedupe_strings,
    _go_function_declarations,
    _infer_go_contracts,
)

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
        return _detect_block_safety_issues(source, _rust_function_blocks(source), "Rust")
    if normalized == "typescript":
        return _detect_block_safety_issues(
            source,
            _typescript_function_blocks(source),
            "TypeScript",
        )
    if normalized == "go":
        return _detect_go_safety_issues(source)
    if normalized == "python":
        return _detect_python_safety_issues(source)
    if normalized == "solidity":
        return _detect_block_safety_issues(
            source,
            _solidity_function_blocks(source),
            "Solidity",
        )
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
        expressions = _return_expressions(body)
        if not expressions and label == "Rust":
            expressions = [_last_rust_expression(body)]
        for expression in expressions:
            issues.extend(_issues_for_expression(name, expression, label))
    return issues

def _detect_go_safety_issues(source: str) -> list[ForeignSafetyIssue]:
    issues: list[ForeignSafetyIssue] = []
    for name, params_text, _return_type, body in _go_function_declarations(source):
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

def _issues_for_expression(
    function_name: str,
    expression: str,
    label: str,
    *,
    dereference_values: set[str] | None = None,
) -> list[ForeignSafetyIssue]:
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
    pattern = re.compile(
        r"function\s+(?P<name>[A-Za-z_$][\w$]*)\s*"
        r"\((?P<params>[^)]*)\)"
        r"(?P<attrs>[^{;]*?)\{",
        re.DOTALL,
    )
    blocks: list[tuple[str, str]] = []
    for match in pattern.finditer(source):
        body = _balanced_brace_body(source, match.end() - 1)
        blocks.append((_safe_identifier(match.group("name")), body))
    return blocks

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
