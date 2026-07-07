"""Foreign-code contract inference helpers for cross-validation."""
from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path
import re
from typing import cast

from agent.config import AgentConfig
from agent.cross_validation_models import (
    ContractParam,
    CrossValidationIssue,
    MumeiContractAtom,
)

def _normalize_foreign_language(language: str) -> str:
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

# 256-bit integer bounds for Solidity uint256/int256 overflow reasoning.
SOLIDITY_UINT256_MAX = 2**256 - 1
SOLIDITY_INT256_MAX = 2**255 - 1
SOLIDITY_INT256_MIN = -(2**255)

def _dedupe_strings(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        stripped = value.strip()
        if stripped and stripped not in deduped:
            deduped.append(stripped)
    return deduped


def _strip_go_rust_literals_and_comments(text: str) -> str:
    def mask(span: str) -> str:
        return "".join("\n" if char == "\n" else " " for char in span)

    def consume_string(index: int, quote: str) -> int:
        i = index + 1
        while i < len(text):
            char = text[i]
            if char == "\\" and i + 1 < len(text):
                i += 2
                continue
            if char == quote:
                return i + 1
            i += 1
        return len(text)

    def consume_char_literal(index: int) -> int:
        i = index + 1
        if i >= len(text) or text[i] == "\n":
            return 0
        if text[i] == "\\":
            i += 1
            if i >= len(text) or text[i] == "\n":
                return 0
            if text[i] in {"x", "u", "U", "n", "r", "t", "0", "\\", "'", '"'}:
                if text[i] in {"u", "U"}:
                    i += 1
                    if i >= len(text) or text[i] != "{":
                        return 0
                    i += 1
                    digits = 0
                    while i < len(text) and text[i] != "}":
                        if text[i] == "\n" or digits > 6 or text[i] not in "0123456789abcdefABCDEF":
                            return 0
                        digits += 1
                        i += 1
                    if digits == 0 or i >= len(text) or text[i] != "}":
                        return 0
                    i += 1
                elif text[i] == "x":
                    i += 1
                    digits = 0
                    while i < len(text) and digits < 2 and text[i] in "0123456789abcdefABCDEF":
                        digits += 1
                        i += 1
                    if digits == 0:
                        return 0
                else:
                    i += 1
            else:
                return 0
        else:
            if text[i] == "'" or text[i] == "\\":
                return 0
            i += 1
        if i < len(text) and text[i] == "'":
            return i + 1
        return 0

    def consume_rust_raw_string(index: int) -> int:
        if text[index] == "b" and index + 1 < len(text) and text[index + 1] == "r":
            prefix = 2
        elif text[index] == "r":
            prefix = 1
        else:
            return 0
        hashes = 0
        cursor = index + prefix
        while cursor < len(text) and text[cursor] == "#":
            hashes += 1
            cursor += 1
        if cursor >= len(text) or text[cursor] != '"':
            return 0
        closing = '"' + ("#" * hashes)
        end = text.find(closing, cursor + 1)
        if end == -1:
            return len(text)
        return end + len(closing)

    stripped: list[str] = []
    i = 0
    while i < len(text):
        if text.startswith("//", i):
            j = text.find("\n", i)
            if j == -1:
                stripped.append(mask(text[i:]))
                break
            stripped.append(mask(text[i:j]))
            stripped.append("\n")
            i = j + 1
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            end = len(text) if j == -1 else j + 2
            stripped.append(mask(text[i:end]))
            i = end
            continue
        raw_end = consume_rust_raw_string(i)
        if raw_end:
            stripped.append(mask(text[i:raw_end]))
            i = raw_end
            continue
        char = text[i]
        if char == '"':
            end = consume_string(i, char)
            stripped.append(mask(text[i:end]))
            i = end
            continue
        if char == "'":
            end = consume_char_literal(i)
            if end:
                stripped.append(mask(text[i:end]))
                i = end
                continue
        if char == "`":
            end = consume_string(i, char)
            stripped.append(mask(text[i:end]))
            i = end
            continue
        stripped.append(char)
        i += 1
    return "".join(stripped)

def _infer_foreign_contracts_with_patterns(code: str, language: str) -> list[MumeiContractAtom]:
    language = _normalize_foreign_language(language)
    if language == "python":
        return _infer_python_contracts(code)
    if language == "rust":
        return _infer_rust_contracts(code)
    if language == "typescript":
        return _infer_typescript_contracts(code)
    if language == "go":
        return _infer_go_contracts(code)
    if language == "solidity":
        return _infer_solidity_contracts(code)
    return []


def _infer_foreign_source_line_map(code: str, language: str) -> dict[str, int]:
    language = _normalize_foreign_language(language)
    if language == "python":
        return _infer_python_source_line_map(code)
    if language == "rust":
        return _infer_regex_source_line_map(
            code,
            re.compile(
                r"(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+"
                r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?:<[^>]+>)?\s*"
                r"\((?P<params>[^)]*)\)\s*(?:->\s*(?P<ret>[^{;\n]+))?",
                flags=re.DOTALL,
            ),
        )
    if language == "go":
        return _infer_regex_source_line_map(
            code,
            re.compile(
                r"func\s+(?:\([^)]*\)\s*)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*"
                r"\((?P<params>[^)]*)\)\s*(?P<ret>[\*\[\]A-Za-z0-9_]+)?\s*\{",
                flags=re.DOTALL,
            ),
        )
    if language == "typescript":
        line_map = _infer_regex_source_line_map(
            code,
            re.compile(
                r"(?:export\s+)?(?:async\s+)?function\s+"
                r"(?P<name>[A-Za-z_$][\w$]*)\s*(?:<[^>]+>)?\s*"
                r"\((?P<params>[^)]*)\)\s*(?:[:{])",
                flags=re.DOTALL,
            ),
        )
        line_map.update(
            _infer_regex_source_line_map(
                code,
                re.compile(
                    r"(?:export\s+)?(?:const|let)\s+"
                    r"(?P<name>[A-Za-z_$][\w$]*)\s*=\s*"
                    r"(?:async\s*)?\((?P<params>[^)]*)\)\s*"
                    r"(?::\s*(?P<ret>[^=]+?))?\s*=>",
                    flags=re.DOTALL,
                ),
            )
        )
        return line_map
    if language == "solidity":
        return _infer_regex_source_line_map(
            code,
            re.compile(
                r"function\s+(?P<name>[A-Za-z_$][\w$]*)\s*"
                r"\((?P<params>[^)]*)\)",
                flags=re.DOTALL,
            ),
        )
    return {}


def _infer_python_source_line_map(code: str) -> dict[str, int]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return {}
    line_map: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            line_map[_safe_identifier(node.name)] = node.lineno
    return line_map


def _infer_regex_source_line_map(code: str, pattern: re.Pattern[str]) -> dict[str, int]:
    line_map: dict[str, int] = {}
    for match in pattern.finditer(code):
        name = _safe_identifier(match.group("name"))
        line_map[name] = code[: match.start("name")].count("\n") + 1
    return line_map


def _with_source_lines(
    issues: list[CrossValidationIssue],
    source_line_map: dict[str, int],
) -> list[CrossValidationIssue]:
    if not source_line_map:
        return issues
    enriched: list[CrossValidationIssue] = []
    for issue in issues:
        if issue.source_line:
            enriched.append(issue)
            continue
        function_name = issue.location or _issue_function_from_text(issue.message)
        source_line = source_line_map.get(function_name, 0)
        enriched.append(replace(issue, source_line=source_line) if source_line else issue)
    return enriched


def _issue_function_from_text(text: str) -> str:
    match = re.search(r"`(?P<name>[A-Za-z_][A-Za-z0-9_]*)`", text)
    return _safe_identifier(match.group("name")) if match else ""


def _infer_foreign_contracts_with_code_to_spec(
    code: str,
    language: str,
    config: AgentConfig,
) -> list[MumeiContractAtom]:
    try:
        from agent.code_to_spec import CodeToSpecConverter

        conversion = CodeToSpecConverter(config).convert_source(code, language)
    except Exception:
        return _infer_foreign_contracts_with_patterns(code, language)
    if conversion.atoms:
        return cast(list[MumeiContractAtom], conversion.atoms)
    return _infer_foreign_contracts_with_patterns(code, language)


def _infer_python_contracts(code: str) -> list[MumeiContractAtom]:
    atoms: list[MumeiContractAtom] = []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return atoms
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            params = [ContractParam(name=arg.arg, type="i64") for arg in node.args.args]
            ensures, return_expr = _python_function_contract(node)
            requires = _safety_requires_for_expression(return_expr)
            atoms.append(
                MumeiContractAtom(
                    name=_safe_identifier(node.name),
                    params=params,
                    return_type="i64",
                    requires=requires,
                    ensures=ensures,
                )
            )
    return atoms


def _python_function_contract(function_node: ast.FunctionDef) -> tuple[str, str]:
    abs_param = _absolute_value_param(function_node)
    if abs_param:
        return f"result >= 0 && (result == {abs_param} or result == -{abs_param})", abs_param
    return_expr = _single_return_expr(function_node)
    return (f"result == {return_expr}" if return_expr else "true", return_expr)


def _absolute_value_param(function_node: ast.FunctionDef) -> str:
    params = [arg.arg for arg in function_node.args.args]
    if len(params) != 1:
        return ""
    param = params[0]
    return_expr = _single_return_expr(function_node)
    if return_expr == f"abs({param})":
        return param
    returns = [node for node in ast.walk(function_node) if isinstance(node, ast.Return)]
    returned = {_normalized_python_return(node.value) for node in returns if node.value is not None}
    if {param, f"-{param}"}.issubset(returned):
        return param
    return ""


def _normalized_python_return(node: ast.AST) -> str:
    try:
        return ast.unparse(node).replace(" ", "")
    except ValueError:
        return ""


def _single_return_expr(function_node: ast.FunctionDef) -> str:
    returns = [node for node in ast.walk(function_node) if isinstance(node, ast.Return)]
    if len(returns) != 1:
        return ""
    value = returns[0].value
    if value is None:
        return ""
    try:
        return ast.unparse(value)
    except ValueError:
        return ""


def _safety_requires_for_expression(expression: str) -> str:
    if not expression:
        return "true"
    requirements: list[str] = []
    try:
        tree = ast.parse(expression, mode="eval")
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)):
                divisor = ast.unparse(node.right)
                requirements.append(f"{divisor} != 0")
    except (SyntaxError, ValueError):
        requirements.extend(_generic_safety_requires_for_expression(expression))
        return " && ".join(_dedupe_strings(requirements)) if requirements else "true"
    requirements.extend(_generic_safety_requires_for_expression(expression))
    return " && ".join(_dedupe_strings(requirements)) if requirements else "true"


def _generic_safety_requires_for_expression(expression: str) -> list[str]:
    requirements: list[str] = []
    for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*(?:/|%)\s*([A-Za-z_][A-Za-z0-9_]*)", expression):
        requirements.append(f"{match.group(2)} != 0")
    for match in re.finditer(
        r"\b(?P<container>[A-Za-z_][A-Za-z0-9_]*)\s*\[\s*(?P<index>[A-Za-z_][A-Za-z0-9_]*)\s*\]",
        expression,
    ):
        container = match.group("container")
        index = match.group("index")
        requirements.append(f"{index} >= 0")
        requirements.append(f"{index} < len_{container}")
    for match in re.finditer(
        r"\b(?P<value>[A-Za-z_][A-Za-z0-9_]*)!?\.(?:length|len|is_empty)\b",
        expression,
    ):
        requirements.append(f"{match.group('value')} != null")
        requirements.append(f"{match.group('value')} != undefined")
    return requirements


def _go_safety_requires_for_expression(
    expression: str,
    param_names: Iterable[str] = (),
) -> str:
    requirements: list[str] = []
    base = _safety_requires_for_expression(expression)
    if base != "true":
        requirements.extend(part.strip() for part in base.split("&&") if part.strip())
    for value in _go_nil_dereference_values(expression, set(param_names)):
        requirements.append(f"{value} != nil")
    requirements.extend(_integer_overflow_requires_for_expression(expression))
    return " && ".join(_dedupe_strings(requirements)) if requirements else "true"


def _go_nil_dereference_values(
    expression: str,
    eligible_values: set[str] | None = None,
) -> list[str]:
    expression = _strip_go_rust_literals_and_comments(expression)
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


def _infer_rust_contracts(code: str) -> list[MumeiContractAtom]:
    atoms: list[MumeiContractAtom] = []
    pattern = re.compile(
        r"(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+"
        r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*"
        r"(?:<[^>]+>)?\s*"
        r"\((?P<params>[^)]*)\)\s*(?:->\s*(?P<ret>[^{;\n]+))?\s*\{(?P<body>.*?)\}",
        flags=re.DOTALL,
    )
    for match in pattern.finditer(code):
        params = _params_from_signature(match.group("params"))
        body = match.group("body")
        return_expr = _last_expression(body)
        safety_expr = _last_expression(_strip_go_rust_literals_and_comments(body))
        atoms.append(
            MumeiContractAtom(
                name=_safe_identifier(match.group("name")),
                params=params,
                return_type="i64" if match.group("ret") else "bool",
                requires=_rust_safety_requires_for_expression(safety_expr),
                ensures=f"result == {return_expr}" if return_expr else "true",
            )
        )
    return atoms


def _infer_solidity_contracts(code: str) -> list[MumeiContractAtom]:
    atoms: list[MumeiContractAtom] = []
    header = re.compile(
        r"function\s+(?P<name>[A-Za-z_$][\w$]*)\s*"
        r"\((?P<params>[^)]*)\)"
        r"(?P<attrs>[^{;]*?)\{",
        flags=re.DOTALL,
    )
    for match in header.finditer(code):
        params, param_types = _solidity_params_from_signature(match.group("params"))
        attrs = match.group("attrs") or ""
        returns_match = re.search(r"returns\s*\((?P<ret>[^)]*)\)", attrs)
        body = _balanced_brace_body(code, match.end() - 1)
        raw_return_expr = _raw_return_statement_expression(body)
        return_expr = _normalize_foreign_expression(raw_return_expr)
        atoms.append(
            MumeiContractAtom(
                name=_safe_identifier(match.group("name")),
                params=params,
                return_type="i64" if returns_match else "bool",
                requires=_solidity_safety_requires_for_expression(
                    raw_return_expr,
                    param_types,
                ),
                ensures=f"result == {return_expr}" if return_expr else "true",
            )
        )
    return atoms


def _solidity_params_from_signature(
    params_text: str,
) -> tuple[list[ContractParam], dict[str, str]]:
    params: list[ContractParam] = []
    param_types: dict[str, str] = {}
    modifiers = {"memory", "calldata", "storage", "payable", "indexed"}
    for index, raw in enumerate(part.strip() for part in params_text.split(",") if part.strip()):
        tokens = [token for token in raw.split() if token.lower() not in modifiers]
        if len(tokens) >= 2:
            type_text, name_text = tokens[0], tokens[-1]
        elif tokens:
            type_text, name_text = tokens[0], f"arg{index}"
        else:
            type_text, name_text = "uint256", f"arg{index}"
        name = _safe_identifier(name_text)
        params.append(
            ContractParam(name=name, type=_solidity_signature_type(type_text))
        )
        param_types[name] = type_text.strip().lower()
    return params, param_types


def _solidity_signature_type(type_text: str) -> str:
    normalized = type_text.strip().removesuffix("[]").lower()
    if normalized in {"bool"}:
        return "bool"
    if normalized in {"string", "bytes"}:
        return "string"
    if normalized.startswith("uint"):
        return "u64"
    return "i64"


def _solidity_type_is_unsigned(type_text: str) -> bool:
    return type_text.strip().lower().startswith("uint")


def _solidity_safety_requires_for_expression(
    expression: str,
    param_types: dict[str, str] | None = None,
) -> str:
    requirements: list[str] = []
    base = _safety_requires_for_expression(expression)
    if base != "true":
        requirements.extend(part.strip() for part in base.split("&&") if part.strip())
    requirements.extend(
        _solidity_overflow_requires_for_expression(expression, param_types)
    )
    return " && ".join(_dedupe_strings(requirements)) if requirements else "true"


def _solidity_overflow_requires_for_expression(
    expression: str,
    param_types: dict[str, str] | None = None,
) -> list[str]:
    param_types = param_types or {}
    requirements: list[str] = []
    for match in re.finditer(
        r"\b(?P<left>[A-Za-z_][A-Za-z0-9_]*)\s*\+\s*(?P<right>[A-Za-z_][A-Za-z0-9_]*)",
        expression,
    ):
        left = match.group("left")
        right = match.group("right")
        unsigned = _solidity_type_is_unsigned(
            param_types.get(left, "")
        ) or _solidity_type_is_unsigned(param_types.get(right, ""))
        # Default to uint256 semantics when the operand types are unknown, as
        # Solidity's most common integer type is unsigned.
        if not param_types or unsigned:
            requirements.append(f"{left} + {right} <= {SOLIDITY_UINT256_MAX}")
            requirements.append(f"{left} + {right} >= 0")
        else:
            requirements.append(f"{left} + {right} <= {SOLIDITY_INT256_MAX}")
            requirements.append(f"{left} + {right} >= {SOLIDITY_INT256_MIN}")
    return requirements


def _rust_safety_requires_for_expression(expression: str) -> str:
    requirements = []
    base = _safety_requires_for_expression(expression)
    if base != "true":
        requirements.extend(part.strip() for part in base.split("&&") if part.strip())
    requirements.extend(_integer_overflow_requires_for_expression(expression))
    return " && ".join(_dedupe_strings(requirements)) if requirements else "true"


def _integer_overflow_requires_for_expression(expression: str) -> list[str]:
    requirements: list[str] = []
    for match in re.finditer(
        r"\b(?P<left>[A-Za-z_][A-Za-z0-9_]*)\s*\+\s*(?P<right>[A-Za-z_][A-Za-z0-9_]*)",
        expression,
    ):
        left = match.group("left")
        right = match.group("right")
        requirements.append(f"{left} + {right} <= 9223372036854775807")
        requirements.append(f"{left} + {right} >= -9223372036854775808")
    return requirements


def _infer_typescript_contracts(code: str) -> list[MumeiContractAtom]:
    atoms: list[MumeiContractAtom] = []
    patterns = [
        re.compile(
            r"(?:export\s+)?(?:async\s+)?function\s+"
            r"(?P<name>[A-Za-z_$][\w$]*)\s*(?:<[^>]+>)?\s*"
            r"\((?P<params>[^)]*)\)\s*(?::\s*(?P<ret>[^{=\n]+))?\s*"
            r"\{(?P<body>.*?)\}",
            flags=re.DOTALL,
        ),
        re.compile(
            r"(?:export\s+)?(?:const|let)\s+"
            r"(?P<name>[A-Za-z_$][\w$]*)\s*=\s*"
            r"(?:async\s*)?\((?P<params>[^)]*)\)\s*"
            r"(?::\s*(?P<ret>[^=]+?))?\s*=>\s*"
            r"(?P<body>\{.*?\}|[^;\n]+)",
            flags=re.DOTALL,
        ),
    ]
    seen: set[tuple[str, int]] = set()
    for pattern in patterns:
        for match in pattern.finditer(code):
            key = (match.group("name"), match.start())
            if key in seen:
                continue
            seen.add(key)
            body = match.group("body") or ""
            raw_return_expr = _typescript_raw_return_expression(body)
            return_expr = _normalize_foreign_expression(raw_return_expr)
            atoms.append(
                MumeiContractAtom(
                    name=_safe_identifier(match.group("name")),
                    params=_params_from_signature(match.group("params")),
                    return_type=_typescript_return_type(match.group("ret") or "number"),
                    requires=_safety_requires_for_expression(raw_return_expr),
                    ensures=f"result == {return_expr}" if return_expr else "true",
                )
            )
    return atoms


def _infer_go_contracts(code: str) -> list[MumeiContractAtom]:
    atoms: list[MumeiContractAtom] = []
    for name, params_text, return_type, body in _go_function_declarations(code):
        params = _params_from_signature(params_text)
        raw_return_expr = _raw_return_statement_expression(body)
        safety_expr = _raw_return_statement_expression(
            _strip_go_rust_literals_and_comments(body)
        )
        return_expr = _normalize_foreign_expression(raw_return_expr)
        atoms.append(
            MumeiContractAtom(
                name=_safe_identifier(name),
                params=params,
                return_type="i64" if return_type else "bool",
                requires=_go_safety_requires_for_expression(
                    safety_expr,
                    [param.name for param in params],
                ),
                ensures=f"result == {return_expr}" if return_expr else "true",
            )
        )
    return atoms


def _go_function_declarations(code: str) -> list[tuple[str, str, str, str]]:
    pattern = re.compile(
        r"func\s+(?:(?P<receiver>\([^)]*\))\s*)?"
        r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*"
        r"\((?P<params>[^)]*)\)\s*(?P<ret>[\*\[\]A-Za-z0-9_]+)?\s*\{",
        flags=re.DOTALL,
    )
    declarations: list[tuple[str, str, str, str]] = []
    for match in pattern.finditer(code):
        body = _balanced_brace_body(code, match.end() - 1)
        receiver = (match.group("receiver") or "").strip()
        receiver = receiver.removeprefix("(").removesuffix(")").strip()
        params = ", ".join(
            part
            for part in (receiver, match.group("params"))
            if part
        )
        declarations.append(
            (
                match.group("name"),
                params,
                match.group("ret") or "",
                body,
            )
        )
    return declarations


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


def _params_from_signature(params_text: str) -> list[ContractParam]:
    params: list[ContractParam] = []
    for index, raw in enumerate(part.strip() for part in params_text.split(",") if part.strip()):
        pieces = raw.split(":")
        name = pieces[0].strip().split()[0].rstrip("?") if pieces[0].strip() else f"arg{index}"
        type_text = pieces[1].strip() if len(pieces) > 1 else "i64"
        params.append(
            ContractParam(
                name=_safe_identifier(name),
                type=_foreign_signature_type(type_text),
            )
        )
    return params


def _foreign_signature_type(type_text: str) -> str:
    normalized = type_text.strip().split("|", 1)[0].strip()
    normalized = normalized.removeprefix("&").removeprefix("mut ").strip()
    normalized = normalized.removeprefix("Promise<").removesuffix(">")
    normalized = normalized.removesuffix("[]")
    lowered = normalized.lower()
    if lowered in {"string", "str", "&str"}:
        return "string"
    if lowered in {"bool", "boolean"}:
        return "bool"
    if lowered in {"float", "double", "f32", "f64"}:
        return "f64"
    if lowered in {"uint", "usize", "u8", "u16", "u32", "u64"}:
        return "u64"
    return "i64"


def _last_expression(body: str) -> str:
    stripped = body.strip().rstrip(";")
    if not stripped:
        return ""
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    if not lines:
        return ""
    return _normalize_foreign_expression(lines[-1].removeprefix("return ").strip())


def _return_statement_expression(body: str) -> str:
    raw = _raw_return_statement_expression(body)
    return _normalize_foreign_expression(raw) if raw else ""


def _raw_return_statement_expression(body: str) -> str:
    matches = list(re.finditer(r"\breturn\s+([^;\n}]+)", body))
    return matches[-1].group(1).strip() if matches else ""


def _typescript_raw_return_expression(body: str) -> str:
    stripped = body.strip()
    if stripped.startswith("{"):
        match = re.search(r"\breturn\s+([^;\n}]+)", stripped)
        return match.group(1).strip() if match else ""
    if stripped.startswith("return "):
        return stripped.removeprefix("return ").rstrip(";").strip()
    return stripped.rstrip(";")


def _typescript_return_type(type_text: str) -> str:
    normalized = type_text.strip()
    if "|" in normalized:
        normalized = normalized.split("|", 1)[0].strip()
    lowered = normalized.lower().removeprefix("promise<").removesuffix(">")
    if lowered in {"boolean", "bool"}:
        return "bool"
    if lowered in {"string", "str"}:
        return "string"
    return "i64"


def _normalize_foreign_expression(expression: str) -> str:
    normalized = expression.replace("&&", "and").replace("||", "or")
    normalized = normalized.replace("===", "==").replace("!==", "!=")
    normalized = re.sub(r"\b([A-Za-z_][A-Za-z0-9_]*)\.length\b", r"len_\1", normalized)
    normalized = re.sub(r"\b([A-Za-z_][A-Za-z0-9_]*)!?\.", r"\1_", normalized)
    return normalized

def _safe_identifier(value: str) -> str:
    safe = re.sub(r"\W+", "_", value.strip())
    safe = safe.strip("_")
    if not safe:
        return "cross_validation_atom"
    if safe[0].isdigit():
        return f"atom_{safe}"
    return safe
