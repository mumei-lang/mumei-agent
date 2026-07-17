"""Foreign-code contract inference helpers for cross-validation."""
from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path
import re
from typing import Callable, cast

from agent import semantic_safety, tree_sitter_extract
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
    if language in tree_sitter_extract.SUPPORTED_LANGUAGES:
        ts_line_map = tree_sitter_extract.function_line_map(
            code, language, _safe_identifier
        )
        if ts_line_map is not None:
            return ts_line_map
    if language == "rust":
        return _infer_regex_source_line_map(
            code,
            re.compile(
                r"(?:pub(?:\([^)]*\))?\s+)?(?:unsafe\s+)?(?:async\s+)?fn\s+"
                r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*"
                r"(?:<[^<>]*(?:<[^<>]*>[^<>]*)*>)?\s*"
                r"\((?P<params>(?:[^()]|\([^)]*\))*)\)\s*"
                r"(?P<ret>[^;{]*?)?\s*\{",
                flags=re.DOTALL,
            ),
        )
    if language == "go":
        return _infer_regex_source_line_map(
            code,
            re.compile(
                r"func\s+(?:\([^)]*\)\s*)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\(",
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
                    r"(?P<name>[A-Za-z_$][\w$]*)\s*(?::\s*[^=]+?)?\s*=\s*"
                    r"(?:async\s*)?\((?P<params>[^)]*)\)\s*"
                    r"(?::\s*(?P<ret>[^=]+?))?\s*=>",
                    flags=re.DOTALL,
                ),
            )
        )
        # Class/object methods do not use the ``function`` keyword.
        line_map.update(
            _infer_regex_source_line_map(
                code,
                re.compile(
                    r"(?m)^\s*(?:abstract\s+)?"
                    r"(?:private\s+|protected\s+|public\s+|static\s+|readonly\s+|async\s+)*"
                    r"(?P<name>(?!(?:if|while|for|switch|catch|with)\b)"
                    r"[A-Za-z_$][\w$]*)\s*"
                    r"\((?P<params>(?:[^()]|\([^)]*\))*)\)\s*"
                    r"(?::\s*(?P<ret>[^{=\n]+?))?\s*\{",
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
                r"\((?P<params>(?:[^()]|\([^)]*\))*)\)",
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


def _is_python_overload_stub(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Detect ``@overload`` stubs and bodies that are just ``...``."""
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id == "overload":
            return True
        if isinstance(decorator, ast.Attribute) and decorator.attr == "overload":
            return True
    if len(node.body) == 1:
        stmt = node.body[0]
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            return stmt.value.value is Ellipsis
    return False


def _infer_python_contracts(code: str) -> list[MumeiContractAtom]:
    atoms: list[MumeiContractAtom] = []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return atoms

    def collect_functions(
        node: ast.AST, in_class: bool = False
    ) -> Iterable[tuple[ast.FunctionDef | ast.AsyncFunctionDef, bool]]:
        for child in getattr(node, "body", []):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield child, in_class
            elif isinstance(child, ast.ClassDef):
                yield from collect_functions(child, in_class=True)

    for node, in_class in collect_functions(tree):
        if _is_python_overload_stub(node):
            continue
        params = _python_params_from_node(node, in_class)
        ensures, return_expr = _python_function_contract(node)
        requires = _safety_requires_for_expression(return_expr)
        return_type = _python_mumei_return_type(node)
        atoms.append(
            MumeiContractAtom(
                name=_safe_identifier(node.name),
                params=params,
                return_type=return_type,
                requires=requires,
                ensures=ensures,
            )
        )
    return atoms


def _is_python_staticmethod(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id == "staticmethod":
            return True
    return False


def _python_params_from_node(
    node: ast.FunctionDef | ast.AsyncFunctionDef, in_class: bool
) -> list[ContractParam]:
    args = node.args.args
    if in_class and args and not _is_python_staticmethod(node):
        first = args[0].arg
        if first in {"self", "cls"}:
            args = args[1:]
    return [ContractParam(name=arg.arg, type="i64") for arg in args]


def _python_function_contract(
    function_node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[str, str]:
    abs_param = _absolute_value_param(function_node)
    if abs_param:
        return f"result >= 0 && (result == {abs_param} or result == -{abs_param})", abs_param
    return_expr = _single_return_expr(function_node)
    return (f"result == {return_expr}" if return_expr else "true", return_expr)


def _direct_returns(node: ast.AST) -> list[ast.Return]:
    """Return ``Return`` nodes in ``node`` that are not inside nested functions/classes."""
    returns: list[ast.Return] = []
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(child, ast.Return):
            returns.append(child)
        returns.extend(_direct_returns(child))
    return returns


def _python_return_values(node: ast.AST) -> list[ast.expr]:
    """Return values of ``Return`` nodes in ``node`` that are not inside nested functions/classes."""
    return [ret.value for ret in _direct_returns(node) if ret.value is not None]


def _python_mumei_return_type(function_node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Return a Mumei return type for a Python function.

    Honors explicit annotations when present; otherwise infers the type from
    the function's return values so unannotated boolean/comparison/string
    returns do not get coerced to ``i64`` and then rejected by Mumei.
    """
    if function_node.returns:
        return _mumei_return_type(ast.unparse(function_node.returns))
    return_values = _python_return_values(function_node)
    if not return_values:
        return "()"
    if len(return_values) == 1:
        return _mumei_type_from_python_value(return_values[0])
    # Multiple returns: use the type if they all agree, otherwise default to i64.
    types = {_mumei_type_from_python_value(value) for value in return_values}
    return types.pop() if len(types) == 1 else "i64"


def _mumei_type_from_python_value(value: ast.AST) -> str:
    """Map a Python AST expression to a Mumei return type string."""
    if isinstance(value, ast.Constant):
        if isinstance(value.value, bool):
            return "bool"
        if isinstance(value.value, int):
            return "i64"
        if isinstance(value.value, float):
            return "f64"
        if isinstance(value.value, str):
            return "string"
        if value.value is None:
            return "()"
        return "i64"
    if isinstance(value, ast.UnaryOp):
        if isinstance(value.op, ast.Not):
            return "bool"
        return _mumei_type_from_python_value(value.operand)
    if isinstance(value, (ast.BoolOp, ast.Compare)):
        return "bool"
    if isinstance(value, ast.BinOp):
        if isinstance(value.op, ast.Div):
            return "f64"
        left = _mumei_type_from_python_value(value.left)
        right = _mumei_type_from_python_value(value.right)
        if isinstance(value.op, ast.Add) and left == "string" and right == "string":
            return "string"
        if left == "f64" or right == "f64":
            return "f64"
        return "i64"
    if isinstance(value, ast.IfExp):
        body = _mumei_type_from_python_value(value.body)
        orelse = _mumei_type_from_python_value(value.orelse)
        return body if body == orelse else "i64"
    if isinstance(value, ast.Call):
        func = value.func
        if isinstance(func, ast.Name) and func.id == "isinstance":
            return "bool"
        if isinstance(func, ast.Name) and func.id in {"len", "abs"}:
            return "i64"
    return "i64"


def _absolute_value_param(function_node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    params = [arg.arg for arg in function_node.args.args]
    if len(params) != 1:
        return ""
    param = params[0]
    return_expr = _single_return_expr(function_node)
    if return_expr == f"abs({param})":
        return param
    returns = _direct_returns(function_node)
    returned = {_normalized_python_return(node.value) for node in returns if node.value is not None}
    if {param, f"-{param}"}.issubset(returned):
        return param
    return ""


def _normalized_python_return(node: ast.AST) -> str:
    try:
        return ast.unparse(node).replace(" ", "")
    except ValueError:
        return ""


def _single_return_expr(function_node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    returns = _direct_returns(function_node)
    if len(returns) != 1:
        return ""
    value = returns[0].value
    if value is None:
        return ""
    try:
        return ast.unparse(value)
    except ValueError:
        return ""


def _safety_requires_for_expression(
    expression: str,
    language: str = "python",
    known_constants: dict[str, int] | None = None,
) -> str:
    known_constants = known_constants or {}
    if not expression:
        return "true"
    canonical = _normalize_foreign_language(language)
    if canonical != "python":
        # Non-Python languages parse via tree-sitter (Layer B stage 2). When a
        # grammar is unavailable or the fragment cannot be parsed, fall back to
        # the regex heuristic, mirroring the Python ``SyntaxError`` fallback.
        findings = tree_sitter_extract.analyze_expression(expression, canonical)
        if findings is not None:
            requirements = _generic_requirements_from_findings(
                findings, canonical, known_constants
            )
            return " && ".join(_dedupe_strings(requirements)) if requirements else "true"
        requirements = _generic_safety_requires_for_expression(
            expression, known_constants, canonical
        )
        return " && ".join(_dedupe_strings(requirements)) if requirements else "true"
    requirements: list[str] = []
    try:
        tree = ast.parse(expression, mode="eval")
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)):
                divisor = ast.unparse(node.right)
                if not semantic_safety.divisor_provably_nonzero(divisor, known_constants):
                    requirements.append(f"{divisor} != 0")
    except (SyntaxError, ValueError):
        requirements.extend(
            _generic_safety_requires_for_expression(
                expression, known_constants, canonical
            )
        )
        return " && ".join(_dedupe_strings(requirements)) if requirements else "true"
    requirements.extend(
        _generic_safety_requires_for_expression(expression, known_constants, canonical)
    )
    return " && ".join(_dedupe_strings(requirements)) if requirements else "true"


def _generic_requirements_from_findings(
    findings: tree_sitter_extract.ExpressionSafety,
    language: str = "typescript",
    known_constants: dict[str, int] | None = None,
) -> list[str]:
    """Divide-by-zero / bounds / null requirements from syntax-tree findings.

    Emits the same requirement strings, in the same order, as the regex
    ``_generic_safety_requires_for_expression`` (division, then bounds, then
    null/undefined), but driven by structural facts rather than text matching.
    The shared semantic model suppresses divisors/indices that resolve to a
    known constant (#296) and only emits a non-null contract when the language
    permits a bare null dereference (#295).
    """
    known_constants = known_constants or {}
    requirements: list[str] = []
    for divisor in findings.divisors:
        if not semantic_safety.divisor_provably_nonzero(divisor, known_constants):
            requirements.append(f"{divisor} != 0")
    for container, index in findings.index_accesses:
        if semantic_safety.known_nonnegative_index(index, known_constants) is None:
            requirements.append(f"{index} >= 0")
        requirements.append(f"{index} < len_{container}")
    for value in findings.length_access_values:
        if semantic_safety.should_flag_null_deref(value, None, language):
            requirements.append(f"{value} != null")
            requirements.append(f"{value} != undefined")
    return requirements


def _i64_overflow_bounds(left: str, right: str) -> list[str]:
    return [
        f"{left} + {right} <= 9223372036854775807",
        f"{left} + {right} >= -9223372036854775808",
    ]


def _addition_pairs_regex(expression: str) -> list[tuple[str, str]]:
    """Regex fallback for ``a + b`` operand pairs (both simple identifiers).

    Skips operands that are call receivers / member accesses (e.g. the
    ``SafeCast`` in ``result + SafeCast.toUint(...)``), which are not integer
    variables and must not be bounded as free integers (#281).
    """
    pairs: list[tuple[str, str]] = []
    for match in re.finditer(
        r"\b(?P<left>[A-Za-z_][A-Za-z0-9_]*)\s*\+\s*(?P<right>[A-Za-z_][A-Za-z0-9_]*)",
        expression,
    ):
        if _operand_is_member_or_call(
            expression, match.span("left")
        ) or _operand_is_member_or_call(expression, match.span("right")):
            continue
        pairs.append((match.group("left"), match.group("right")))
    return pairs


def _generic_safety_requires_for_expression(
    expression: str,
    known_constants: dict[str, int] | None = None,
    language: str = "typescript",
) -> list[str]:
    known_constants = known_constants or {}
    requirements: list[str] = []
    for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*(?:/|%)\s*([A-Za-z_][A-Za-z0-9_]*)", expression):
        divisor = match.group(2)
        if not semantic_safety.divisor_provably_nonzero(divisor, known_constants):
            requirements.append(f"{divisor} != 0")
    for match in re.finditer(
        r"\b(?P<container>[A-Za-z_][A-Za-z0-9_]*)\s*\[\s*(?P<index>[A-Za-z_][A-Za-z0-9_]*)\s*\]",
        expression,
    ):
        container = match.group("container")
        index = match.group("index")
        if semantic_safety.known_nonnegative_index(index, known_constants) is None:
            requirements.append(f"{index} >= 0")
        requirements.append(f"{index} < len_{container}")
    for match in re.finditer(
        r"\b(?P<value>[A-Za-z_][A-Za-z0-9_]*)!?\.(?:length|len|is_empty)\b",
        expression,
    ):
        value = match.group("value")
        if semantic_safety.should_flag_null_deref(value, None, language):
            requirements.append(f"{value} != null")
            requirements.append(f"{value} != undefined")
    return requirements


def _go_safety_requires_for_expression(
    expression: str,
    param_names: Iterable[str] = (),
    known_constants: dict[str, int] | None = None,
) -> str:
    requirements: list[str] = []
    base = _safety_requires_for_expression(expression, "go", known_constants)
    if base != "true":
        requirements.extend(part.strip() for part in base.split("&&") if part.strip())
    for value in _go_nil_dereference_values(expression, set(param_names)):
        requirements.append(f"{value} != nil")
    requirements.extend(_integer_overflow_requires_for_expression(expression, "go"))
    return " && ".join(_dedupe_strings(requirements)) if requirements else "true"


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
    expression = _strip_go_rust_literals_and_comments(expression)
    values: list[str] = []
    for match in re.finditer(r"\*\s*(?P<value>[A-Za-z_][A-Za-z0-9_]*)", expression):
        values.append(match.group("value"))
    for match in re.finditer(
        r"\b(?P<value>[A-Za-z_][A-Za-z0-9_]*)\s*\.",
        expression,
    ):
        values.append(match.group("value"))
    return values


def _advance_past_rust_tick(source: str, i: int) -> int:
    """Skip a Rust char literal or lifetime starting at ``source[i] == "'"``.

    Char literals are ``'x'`` or escaped forms such as ``'\\''``.  Lifetimes
    such as ``'a`` or ``'static`` have no closing single quote.
    """
    if source[i] != "'":
        return i + 1
    if i + 1 < len(source) and source[i + 1] == "\\":
        # escaped char literal: '\?', '\'', '\\', etc.
        j = i + 2
        while j < len(source):
            if source[j] == "\\":
                j += 2
                continue
            if source[j] == "'":
                return j + 1
            j += 1
        return len(source)
    if i + 2 < len(source) and source[i + 2] == "'" and source[i + 1] != "\\":
        # plain char literal 'x'
        return i + 3
    # lifetime 'name
    j = i + 1
    while j < len(source) and (source[j].isalnum() or source[j] == "_"):
        j += 1
    return j


def _skip_rust_whitespace_and_comments(source: str, start: int) -> int:
    i = start
    while i < len(source):
        ch = source[i]
        if ch.isspace():
            i += 1
            continue
        if source[i : i + 2] == "//":
            j = source.find("\n", i + 2)
            i = len(source) if j == -1 else j
            continue
        if source[i : i + 2] == "/*":
            j = source.find("*/", i + 2)
            i = len(source) if j == -1 else j + 2
            continue
        break
    return i


def _find_rust_balanced(
    source: str, start: int, open_char: str, close_char: str
) -> int | None:
    """Return the index of the matching ``close_char`` for ``source[start]``.

    Skips Rust line/block comments and string/char literals.  When matching
    ``<...>`` pairs, the ``>`` in ``->`` and ``=>`` tokens is ignored so trait
    bounds such as ``FnOnce() -> T`` do not close the generic list early.
    """
    if start >= len(source) or source[start] != open_char:
        return None
    depth = 1
    i = start + 1
    while i < len(source):
        ch = source[i]
        if ch == "/" and i + 1 < len(source):
            if source[i + 1] == "/":
                j = source.find("\n", i + 2)
                i = len(source) if j == -1 else j
                continue
            if source[i + 1] == "*":
                j = source.find("*/", i + 2)
                i = len(source) if j == -1 else j + 2
                continue
        if ch == '"':
            i += 1
            while i < len(source):
                if source[i] == "\\":
                    i += 2
                    continue
                if source[i] == '"':
                    i += 1
                    break
                i += 1
            continue
        if ch == "'":
            i = _advance_past_rust_tick(source, i)
            continue
        if close_char == ">" and ch == ">" and i > 0 and source[i - 1] in {"-", "="}:
            i += 1
            continue
        if ch == open_char:
            depth += 1
        elif ch == close_char:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def _find_rust_body_start(source: str, start: int) -> int | None:
    """Return the index of the next ``{`` or ``;`` outside comments/strings."""
    i = start
    while i < len(source):
        ch = source[i]
        if ch.isspace():
            i += 1
            continue
        if source[i : i + 2] == "//":
            j = source.find("\n", i + 2)
            i = len(source) if j == -1 else j
            continue
        if source[i : i + 2] == "/*":
            j = source.find("*/", i + 2)
            i = len(source) if j == -1 else j + 2
            continue
        if ch == '"':
            i += 1
            while i < len(source):
                if source[i] == "\\":
                    i += 2
                    continue
                if source[i] == '"':
                    i += 1
                    break
                i += 1
            continue
        if ch == "'":
            i = _advance_past_rust_tick(source, i)
            continue
        if ch in {"{", ";"}:
            return i
        i += 1
    return None


def _strip_rust_where_clause(return_text: str) -> str:
    """Remove a trailing ``where`` clause from a Rust return type."""
    depth = 0
    in_string = False
    quote = ""
    i = 0
    while i < len(return_text):
        ch = return_text[i]
        if in_string:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                in_string = False
            i += 1
            continue
        if ch in {'"', "'"}:
            in_string = True
            quote = ch
            i += 1
            continue
        if ch == "<":
            depth += 1
        elif ch == ">":
            # Ignore -> and => tokens.
            if not (i > 0 and return_text[i - 1] in {"-", "="}):
                depth = max(0, depth - 1)
        if depth == 0 and return_text.startswith("where", i):
            after = i + 5
            if (after >= len(return_text) or return_text[after].isspace()) and (
                i == 0 or return_text[i - 1].isspace()
            ):
                return return_text[:i].strip()
        i += 1
    return return_text


def _rust_parse_signature(
    source: str, name_end: int
) -> tuple[str, str, int] | None:
    """Parse a Rust function signature starting just after the function name.

    Returns ``(params_text, return_type, body_start)``.  ``return_type`` may be an
    empty string if the function returns ``()``.  Returns ``None`` when the text
    at ``name_end`` is not a valid function signature.
    """
    i = _skip_rust_whitespace_and_comments(source, name_end)
    if i >= len(source):
        return None
    if source[i] == "<":
        generic_end = _find_rust_balanced(source, i, "<", ">")
        if generic_end is None:
            return None
        i = _skip_rust_whitespace_and_comments(source, generic_end + 1)
        if i >= len(source):
            return None
    if source[i] != "(":
        return None
    params_end = _find_rust_balanced(source, i, "(", ")")
    if params_end is None:
        return None
    params_text = source[i + 1 : params_end]
    i = _skip_rust_whitespace_and_comments(source, params_end + 1)
    if i >= len(source):
        return None
    return_type = ""
    if source.startswith("->", i):
        i += 2
        i = _skip_rust_whitespace_and_comments(source, i)
        body_start = _find_rust_body_start(source, i)
        if body_start is None:
            return None
        if source[body_start] == ";":
            return params_text, "", body_start
        return_type = _strip_rust_where_clause(source[i : body_start].strip())
    elif source[i] == "{":
        return params_text, "", i
    else:
        return None
    return params_text, return_type, body_start


def _infer_rust_contracts(code: str) -> list[MumeiContractAtom]:
    atoms: list[MumeiContractAtom] = []
    known_constants = semantic_safety.collect_declared_constants(code, "rust")
    name_pattern = re.compile(
        r"(?:pub(?:\([^)]*\))?\s+)?(?:unsafe\s+)?(?:async\s+)?fn\s+"
        r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*",
        flags=re.DOTALL,
    )
    for match in name_pattern.finditer(code):
        parsed = _rust_parse_signature(code, match.end())
        if parsed is None:
            continue
        params_text, return_type, body_start = parsed
        body = _balanced_brace_body(code, body_start)
        params = _params_from_signature(params_text)
        return_expr = _last_expression(body)
        safety_expr = _last_expression(_strip_go_rust_literals_and_comments(body))
        atoms.append(
            MumeiContractAtom(
                name=_safe_identifier(match.group("name")),
                params=params,
                return_type=_mumei_return_type(return_type),
                requires=_rust_safety_requires_for_expression(
                    safety_expr, known_constants
                ),
                ensures=f"result == {return_expr}" if return_expr else "true",
            )
        )
    return atoms


def _infer_solidity_contracts(code: str) -> list[MumeiContractAtom]:
    atoms: list[MumeiContractAtom] = []
    known_constants = semantic_safety.collect_declared_constants(code, "solidity")
    header = re.compile(
        r"function\s+(?P<name>[A-Za-z_$][\w$]*)\s*"
        r"\((?P<params>(?:[^()]|\([^)]*\))*)\)"
        r"(?P<attrs>[^{;]*?)(?P<delim>[{;])",
        flags=re.DOTALL,
    )
    for match in header.finditer(code):
        params, param_types = _solidity_params_from_signature(match.group("params"))
        attrs = match.group("attrs") or ""
        returns_match = re.search(r"returns\s*\((?P<ret>[^)]*)\)", attrs)
        is_interface = match.group("delim") == ";"
        if is_interface:
            raw_return_expr = ""
            return_expr = ""
            requires = "true"
            ensures = "true"
        else:
            body = _balanced_brace_body(code, match.end() - 1)
            raw_return_expr = _raw_return_statement_expression(body)
            return_expr = _normalize_foreign_expression(raw_return_expr)
            requires = _solidity_safety_requires_for_expression(
                raw_return_expr,
                param_types,
                known_constants,
            )
            ensures = f"result == {return_expr}" if return_expr else "true"
        atoms.append(
            MumeiContractAtom(
                name=_safe_identifier(match.group("name")),
                params=params,
                return_type=_mumei_return_type(
                    returns_match.group("ret") if returns_match else None,
                    solidity_modifiers=True,
                ),
                requires=requires,
                ensures=ensures,
            )
        )
    return atoms


def _solidity_params_from_signature(
    params_text: str,
) -> tuple[list[ContractParam], dict[str, str]]:
    params: list[ContractParam] = []
    param_types: dict[str, str] = {}
    modifiers = {"memory", "calldata", "storage", "payable", "indexed"}
    for index, raw in enumerate(part for part in _split_signature_params(params_text) if part.strip()):
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
    known_constants: dict[str, int] | None = None,
) -> str:
    requirements: list[str] = []
    base = _safety_requires_for_expression(expression, "solidity", known_constants)
    if base != "true":
        requirements.extend(part.strip() for part in base.split("&&") if part.strip())
    requirements.extend(
        _solidity_overflow_requires_for_expression(expression, param_types)
    )
    return " && ".join(_dedupe_strings(requirements)) if requirements else "true"


def _operand_is_member_or_call(expression: str, span: tuple[int, int]) -> bool:
    """True when the identifier at ``span`` is a member access or call.

    ``result + SafeCast.toUint(...)`` must not treat ``SafeCast`` as an integer
    addend: it is the receiver of a method call, not a variable. Modeling it as
    a free ``uint256`` produces bogus overflow counterexamples (#281).
    """
    start, end = span
    after = expression[end:].lstrip()
    if after[:1] in {".", "("}:
        return True
    before = expression[:start].rstrip()
    return before[-1:] == "."


def _solidity_overflow_requires_for_expression(
    expression: str,
    param_types: dict[str, str] | None = None,
) -> list[str]:
    param_types = param_types or {}
    findings = tree_sitter_extract.analyze_expression(expression, "solidity")
    additions = (
        list(findings.additions)
        if findings is not None
        else _addition_pairs_regex(expression)
    )
    requirements: list[str] = []
    for left, right in additions:
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


def _rust_safety_requires_for_expression(
    expression: str,
    known_constants: dict[str, int] | None = None,
) -> str:
    requirements = []
    base = _safety_requires_for_expression(expression, "rust", known_constants)
    if base != "true":
        requirements.extend(part.strip() for part in base.split("&&") if part.strip())
    requirements.extend(_integer_overflow_requires_for_expression(expression, "rust"))
    return " && ".join(_dedupe_strings(requirements)) if requirements else "true"


def _integer_overflow_requires_for_expression(
    expression: str, language: str = "rust"
) -> list[str]:
    findings = tree_sitter_extract.analyze_expression(expression, language)
    additions = (
        list(findings.additions)
        if findings is not None
        else _addition_pairs_regex(expression)
    )
    requirements: list[str] = []
    for left, right in additions:
        requirements.extend(_i64_overflow_bounds(left, right))
    return requirements


def _infer_typescript_contracts(code: str) -> list[MumeiContractAtom]:
    atoms: list[MumeiContractAtom] = []
    known_constants = semantic_safety.collect_declared_constants(code, "typescript")
    # Each pattern is paired with a predicate that decides whether the body is
    # an arrow-function expression body (no braces).  Function and class-method
    # bodies are never expression bodies, while arrow functions may use either
    # form.
    patterns: list[tuple[re.Pattern[str], Callable[[str], bool]]] = [
        (
            re.compile(
                r"(?:export\s+)?(?:async\s+)?function\s+"
                r"(?P<name>[A-Za-z_$][\w$]*)\s*(?:<[^>]+>)?\s*"
                r"\((?P<params>[^)]*)\)\s*(?::\s*(?P<ret>[^{=\n]+))?\s*"
                r"\{(?P<body>.*?)\}",
                flags=re.DOTALL,
            ),
            lambda raw: False,
        ),
        (
            re.compile(
                r"(?:export\s+)?(?:const|let)\s+"
                r"(?P<name>[A-Za-z_$][\w$]*)\s*(?::\s*(?P<vartype>[^=]+?))?\s*=\s*"
                r"(?:async\s*)?\((?P<params>[^)]*)\)\s*"
                r"(?::\s*(?P<ret>[^=]+?))?\s*=>\s*"
                r"(?P<body>\{.*?\}|[^;\n]+)",
                flags=re.DOTALL,
            ),
            lambda raw: not raw.startswith("{"),
        ),
        # Class/object methods do not use the ``function`` keyword.
        (
            re.compile(
                r"(?m)^\s*(?:abstract\s+)?"
                r"(?:private\s+|protected\s+|public\s+|static\s+|readonly\s+|async\s+)*"
                r"(?P<name>(?!(?:if|while|for|switch|catch|with)\b)"
                r"[A-Za-z_$][\w$]*)\s*"
                r"\((?P<params>(?:[^()]|\([^)]*\))*)\)\s*"
                r"(?::\s*(?P<ret>[^{=\n]+?))?\s*"
                r"\{(?P<body>.*?)\}",
                flags=re.DOTALL,
            ),
            lambda raw: False,
        ),
    ]
    seen: set[tuple[str, int]] = set()
    for pattern, is_expr_fn in patterns:
        for match in pattern.finditer(code):
            key = (match.group("name"), match.start())
            if key in seen:
                continue
            seen.add(key)
            raw_body = match.group("body") or ""
            is_expression_body = is_expr_fn(raw_body)
            # The regex patterns are non-greedy and stop at the first ``}``.
            # Re-extract the body with proper brace balancing so nested blocks
            # and type literals (``{ [key: string]: unknown }``) do not truncate.
            body_start = match.start("body")
            body = raw_body
            if raw_body.startswith("{"):
                body = _balanced_brace_body(code, body_start)
            elif body_start > 0 and code[body_start - 1] == "{":
                body = _balanced_brace_body(code, body_start - 1)
            raw_return_expr = _typescript_raw_return_expression(body, is_expression_body)
            return_expr = _normalize_foreign_expression(raw_return_expr)
            atoms.append(
                MumeiContractAtom(
                    name=_safe_identifier(match.group("name")),
                    params=_params_from_signature(match.group("params")),
                    return_type=_typescript_return_type(match.group("ret") or "number"),
                    requires=_safety_requires_for_expression(
                        raw_return_expr, "typescript", known_constants
                    ),
                    ensures=f"result == {return_expr}" if return_expr else "true",
                )
            )
    return atoms


def _infer_go_contracts(code: str) -> list[MumeiContractAtom]:
    atoms: list[MumeiContractAtom] = []
    known_constants = semantic_safety.collect_declared_constants(code, "go")
    for name, params_text, return_type, body in _go_function_declarations(code):
        params = _params_from_signature(params_text)
        # Only params whose declared Go type is nillable may carry a `!= nil`
        # precondition; value types (e.g. `reflect.Value`) can never be nil, so
        # inferring one produces a false `refuted` verdict (#295).
        nillable_names = _go_nillable_param_names(params_text)
        raw_return_expr = _raw_return_statement_expression(body)
        safety_expr = _raw_return_statement_expression(
            _strip_go_rust_literals_and_comments(body)
        )
        return_expr = _normalize_foreign_expression(raw_return_expr)
        atoms.append(
            MumeiContractAtom(
                name=_safe_identifier(name),
                params=params,
                return_type=_mumei_return_type(return_type),
                requires=_go_safety_requires_for_expression(
                    safety_expr,
                    [param.name for param in params if param.name in nillable_names],
                    known_constants,
                ),
                ensures=f"result == {return_expr}" if return_expr else "true",
            )
        )
    # Assembly forward declarations and other external function signatures have
    # no Go body; emit them as trusted atoms.
    for name, params_text, return_type, _start in _go_external_declarations(code):
        atoms.append(
            MumeiContractAtom(
                name=_safe_identifier(name),
                params=_params_from_signature(params_text),
                return_type=_mumei_return_type(return_type),
                requires="true",
                ensures="true",
            )
        )
    return atoms


def _go_function_declarations(code: str) -> list[tuple[str, str, str, str]]:
    pattern = re.compile(
        r"func\s+(?:(?P<receiver>\([^)]*\))\s*)?"
        r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*"
        r"\((?P<params>[^)]*)\)\s*"
        r"(?P<ret>(?:\([^)]*\)|[^{]+))?\s*\{",
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


def _go_external_declarations(code: str) -> list[tuple[str, str, str, int]]:
    """Return Go function signatures that have no body (assembly forward declarations)."""
    pattern = re.compile(
        r"(?:^[ \t]*//[^\n]*\n)*"
        r"^[ \t]*func[ \t]+(?:(?P<receiver>\([^)]*\))[ \t]*)?"
        r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)[ \t]*"
        r"\((?P<params>[^)]*)\)[ \t]*"
        r"(?P<ret>(?:\([^)]*\)|[^{;\n/]+?))?"
        r"[ \t]*(?://[^\n]*)?$",
        flags=re.MULTILINE,
    )
    declarations: list[tuple[str, str, str, int]] = []
    for match in pattern.finditer(code):
        pos = match.end()
        while pos < len(code):
            ch = code[pos]
            if ch.isspace():
                pos += 1
                continue
            if code.startswith("//", pos):
                newline = code.find("\n", pos)
                pos = newline + 1 if newline != -1 else len(code)
                continue
            break
        # A real function definition has a ``{`` body; skip those.
        if pos < len(code) and code[pos] == "{":
            continue
        receiver = (match.group("receiver") or "").strip()
        receiver = receiver.removeprefix("(").removesuffix(")").strip()
        params = ", ".join(
            part for part in (receiver, match.group("params")) if part
        )
        declarations.append(
            (
                match.group("name"),
                params,
                (match.group("ret") or "").strip(),
                match.start(),
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


def _split_signature_params(params_text: str) -> list[str]:
    """Split a parameter list on top-level commas, ignoring commas inside
    parentheses, brackets, braces, and angle brackets.

    Naively splitting on ``,`` misparses Rust generics such as
    ``table: impl IntoIterator<Item = (K, &'a V)> + 'a,`` into multiple
    spurious parameters.
    """
    parts: list[str] = []
    start = 0
    depth = 0
    n = len(params_text)
    i = 0
    while i < n:
        ch = params_text[i]
        if ch in "([{<":
            depth += 1
        elif ch in ")]}":
            if depth > 0:
                depth -= 1
        elif ch == ">":
            # Avoid treating ``->`` or ``>=`` as an angle-bracket close.
            if i > 0 and params_text[i - 1] in "-=":
                pass
            elif depth > 0:
                depth -= 1
        elif ch == "," and depth == 0:
            parts.append(params_text[start:i].strip())
            start = i + 1
        i += 1
    tail = params_text[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def _params_from_signature(params_text: str) -> list[ContractParam]:
    params: list[ContractParam] = []
    for index, raw in enumerate(_split_signature_params(params_text)):
        if not raw:
            continue
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


# Solidity storage-location modifiers that can appear in return-type declarations.
_SOLIDITY_MODIFIER_TOKENS = {"memory", "calldata", "storage", "payable", "indexed"}


def _mumei_return_type(
    type_text: str | None,
    *,
    solidity_modifiers: bool = False,
) -> str:
    """Map a foreign-language return-type string to a Mumei return type.

    Void/unit/None annotations become ``()`` so the agent does not emit
    ``result``-bearing postconditions for functions that do not return a value.
    Tuple return types (e.g. Go ``(bool, error)``) are reduced to the first
    component because the contract-inference path only models a single return
    expression.
    """
    if not type_text:
        return "()"
    normalized = type_text.strip()
    if normalized.startswith("(") and normalized.endswith(")"):
        normalized = normalized[1:-1].strip()
    if "," in normalized:
        normalized = normalized.split(",")[0].strip()
    if not normalized:
        return "()"
    lowered = normalized.lower()
    if lowered in {"()", "void", "unit", "none", "nonetype"}:
        return "()"
    if solidity_modifiers:
        tokens = [t for t in normalized.split() if t.lower() not in _SOLIDITY_MODIFIER_TOKENS]
        normalized = " ".join(tokens) if tokens else normalized
    return _foreign_signature_type(normalized)


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


# Go nillability is decided by the shared type predicate so the nil-dereference
# heuristic and the value-type exclusion (#295) use one source of truth.
_GO_NILLABLE_TYPE_RE = semantic_safety._GO_NILLABLE_TYPE_RE


def _go_type_is_nillable(raw_type: str) -> bool:
    return semantic_safety.go_type_is_nillable(raw_type)


def _go_nillable_param_names(params_text: str) -> set[str]:
    """Names of Go params/receiver whose declared type can actually be nil.

    Go params are ``name type``; the type (everything after the name) decides
    nillability. Grouped names sharing a trailing type (``a, b *T``) only bind
    the type to the last name, so the untyped leaders are conservatively
    omitted rather than assumed nillable.
    """
    names: set[str] = set()
    for raw in _split_params(params_text):
        raw = raw.strip()
        if not raw:
            continue
        pieces = raw.split()
        if len(pieces) < 2:
            continue
        name_text, raw_type = pieces[0], " ".join(pieces[1:])
        if _go_type_is_nillable(raw_type):
            names.add(_safe_identifier(name_text))
    return names


def _last_expression(body: str) -> str:
    stripped = body.strip().rstrip(";")
    if not stripped:
        return ""
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    while lines:
        candidate = lines.pop().removeprefix("return ").strip().rstrip(";")
        if not candidate or re.fullmatch(r"[\)\}\];,]+", candidate):
            continue
        # A trailing comma or semicolon usually means the expression continues
        # on the next line, so this line is not a complete tail expression.
        if candidate.endswith((",", ";")):
            continue
        normalized = _normalize_foreign_expression(candidate)
        try:
            tree = ast.parse(normalized, mode="eval")
        except (SyntaxError, ValueError):
            continue
        # A line such as ``.0`` is valid Python as a float literal, but in
        # foreign code it is a fragment of a multi-line method/tuple chain
        # (e.g. Rust ``std::mem::take(...).0.into_iter()...``). Do not treat
        # a leading-dot numeric literal as a complete tail expression.
        if (
            normalized.lstrip().startswith(".")
            and isinstance(tree.body, ast.Constant)
            and isinstance(tree.body.value, (int, float, complex))
        ):
            continue
        return normalized
    return ""


def _is_multi_value_return_expression(expr: str) -> bool:
    """True when ``expr`` returns more than one value (Go tuple, Solidity tuple).

    Ignores commas inside nested parentheses, brackets, or braces so that
    single composite literals and function calls are not mistaken for multi-value
    returns.
    """
    expr = expr.strip()
    # Strip one matching outer pair of parentheses so that ``(a, b)`` is treated
    # the same as ``a, b``.
    if expr.startswith("(") and expr.endswith(")"):
        depth = 0
        for i, ch in enumerate(expr):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    if i == len(expr) - 1:
                        expr = expr[1:-1].strip()
                    break
    depth = 0
    for ch in expr:
        if ch in "([{":
            depth += 1
        elif ch in "])}" and depth > 0:
            depth -= 1
        elif ch == "," and depth == 0:
            return True
    return False


def _return_statement_expression(body: str) -> str:
    raw = _raw_return_statement_expression(body)
    return _normalize_foreign_expression(raw) if raw else ""


def _raw_return_statement_expression(body: str) -> str:
    """Return the expression from the last ``return`` statement in ``body``.

    Stops at the end of the statement, balancing ``()``, ``[]`` and ``{}`` so
    that composite/struct literals such as ``&systemTimer{t, ch}`` or
    ``BlockNumberOrHash{number: blockNr}`` are captured in full instead of
    being truncated at the first ``}``.

    If the body contains more than one ``return`` we cannot infer a single
    deterministic postcondition, so we return the empty string and let the
    caller default ``ensures`` to ``true``.

    Multi-value returns (e.g. Go ``return sum, carryOut != 0`` or Solidity
    ``return (a, b);``) cannot be expressed as a single ``result`` equality, so
    they are also normalised to the empty string.
    """
    stripped = _strip_go_rust_literals_and_comments(body)
    returns: list[re.Match[str]] = []
    for match in re.finditer(r"\breturn\b", stripped):
        end = match.end()
        if end < len(stripped) and (stripped[end].isalnum() or stripped[end] == "_"):
            continue
        returns.append(match)
    if not returns:
        return ""
    # Multiple exits (e.g. early ``return false`` inside ``if``/``for``) do not
    # have a single tail expression that describes every path.
    if len(returns) > 1:
        return ""

    last_match = returns[-1]
    start = last_match.end()
    depth = 0
    for index in range(start, len(stripped)):
        ch = stripped[index]
        if ch in "([{":
            depth += 1
        elif ch in "])}" and depth > 0:
            depth -= 1
        elif ch in ";\n" and depth == 0:
            if _is_multi_value_return_expression(stripped[start:index].strip()):
                return ""
            return body[start:index].strip()
    if _is_multi_value_return_expression(stripped[start:].strip()):
        return ""
    return body[start:].strip()


def _typescript_raw_return_expression(body: str, is_expression_body: bool = False) -> str:
    """Return the expression from the last ``return`` statement in ``body``.

    For block-bodied functions this walks from the last ``return`` keyword,
    balancing ``()``, ``[]`` and ``{}`` so composite literals and parenthesised
    expressions are captured in full.  For arrow functions with an expression
    body (no braces), the whole expression is returned.

    If the body contains more than one top-level ``return`` we cannot infer a
    single deterministic postcondition, so we return the empty string and let the
    caller default ``ensures`` to ``true``.
    """
    if is_expression_body:
        return body.strip().rstrip(";").strip()

    stripped_search = _strip_go_rust_literals_and_comments(body)
    returns: list[int] = []
    # Brace depth counts all (), [] and {}.  function_scope counts how many of
    # those {} belong to nested arrow/function bodies; returns inside them are
    # exits from the inner function, not from the function we are analysing.
    depth = 0
    function_scope = 0
    curly_stack: list[bool] = []
    arrow_pending = False
    arrow_token_end = -1
    arrow_depth = 0
    function_pending = False
    function_keyword_depth = 0
    prev_non_space = ""
    n = len(stripped_search)
    i = 0
    while i < n:
        ch = stripped_search[i]
        if ch in "([{":
            if ch == "{":
                is_func = False
                if arrow_pending and depth == arrow_depth:
                    is_func = True
                    function_scope += 1
                    arrow_pending = False
                elif (
                    function_pending
                    and depth == function_keyword_depth
                    and prev_non_space != ":"
                ):
                    is_func = True
                    function_scope += 1
                    function_pending = False
                curly_stack.append(is_func)
            depth += 1
        elif ch in "])}" and depth > 0:
            if ch == "}" and curly_stack:
                was_func = curly_stack.pop()
                if was_func:
                    function_scope -= 1
            depth -= 1
        elif (
            ch == "r"
            and function_scope == 0
            and i + 6 <= n
            and stripped_search[i : i + 6] == "return"
        ):
            end = i + 6
            word_after = end < n and (
                stripped_search[end].isalnum() or stripped_search[end] == "_"
            )
            word_before = i > 0 and (
                stripped_search[i - 1].isalnum() or stripped_search[i - 1] == "_"
            )
            property_name = end < n and stripped_search[end] == ":"
            if not word_after and not word_before and not property_name:
                returns.append(i)
            i = end - 1
        elif (
            ch == ">"
            and i > 0
            and stripped_search[i - 1] == "="
            and not (i > 1 and stripped_search[i - 2] == "=")
        ):
            # Arrow function token `=>`.  The body may be a block `{ ... }` or an
            # expression; we only enter a new function scope when the next
            # non-space token is `{`.
            arrow_pending = True
            arrow_token_end = i
            arrow_depth = depth
        elif (
            i + 8 <= n
            and stripped_search[i : i + 8] == "function"
            and (i == 0 or not (stripped_search[i - 1].isalnum() or stripped_search[i - 1] == "_"))
            and (i + 8 == n or not (stripped_search[i + 8].isalnum() or stripped_search[i + 8] == "_"))
        ):
            function_pending = True
            function_keyword_depth = depth
            i += 7

        # Cancel a pending arrow expression body when we see the first
        # non-space token after `=>` and it is not `{`.
        if arrow_pending and i > arrow_token_end and not ch.isspace() and ch != "{":
            arrow_pending = False

        if not ch.isspace():
            prev_non_space = ch
        i += 1
    if not returns:
        return ""
    # Multiple top-level returns (e.g. ``if (...) { return x } return y``) do
    # not have a single tail expression that describes every exit path.
    if len(returns) > 1:
        return ""

    last_return = returns[-1]
    start = last_return + 6
    depth = 0
    for index in range(start, len(stripped_search)):
        ch = stripped_search[index]
        if ch in "([{":
            depth += 1
        elif ch in "])}" and depth > 0:
            depth -= 1
        elif ch in ";\n" and depth == 0:
            return body[start:index].strip()
    return body[start:].strip()


def _typescript_return_type(type_text: str) -> str:
    normalized = type_text.strip()
    if "|" in normalized:
        normalized = normalized.split("|", 1)[0].strip()
    lowered = normalized.lower().removeprefix("promise<").removesuffix(">")
    if lowered in {"boolean", "bool"}:
        return "bool"
    if lowered in {"string", "str"}:
        return "string"
    # TypeScript type predicates (``value is SomeType``) and assertion
    # signatures (``asserts value is SomeType``) are always boolean-like.
    if re.search(r"\bis\s", lowered) or lowered.startswith("asserts "):
        return "bool"
    return "i64"


def _is_regex_context(prefix: str) -> bool:
    """Return whether a ``/`` at the current position can start a JS/TS regex literal.

    This is a conservative heuristic based on the previous significant token.
    Regex literals are allowed after operators, delimiters, and certain keywords;
    they are not allowed after value tokens such as identifiers, literals,
    closing brackets, or postfix ``++``/``--``.
    """
    text = prefix.rstrip()
    if text.endswith("..."):
        return True
    i = len(text) - 1
    while i >= 0 and text[i].isspace():
        i -= 1
    if i < 0:
        return True
    ch = text[i]
    # Value-like closing brackets and quotes
    if ch in ")}]\"'`":
        return False
    # Numbers (including a trailing dot)
    if ch.isdigit() or ch == ".":
        return False
    # Identifiers or keywords
    if ch.isalnum() or ch in "$_":
        start = i
        while i >= 0 and (text[i].isalnum() or text[i] in "$_"):
            i -= 1
        word = text[i + 1 : start + 1].lower()
        if word in {
            "return",
            "typeof",
            "void",
            "delete",
            "case",
            "else",
            "await",
            "yield",
            "new",
            "in",
            "of",
            "instanceof",
            "do",
            "while",
            "for",
            "if",
            "switch",
            "with",
            "catch",
            "throw",
            "then",
        }:
            return True
        # Value keywords and all other identifiers are value tokens
        return False
    # ++ / -- are postfix after a value, prefix otherwise
    if ch in "+-":
        if i - 1 >= 0 and text[i - 1] == ch:
            before = i - 2
            while before >= 0 and text[before].isspace():
                before -= 1
            if before < 0:
                return True
            bch = text[before]
            if bch.isalnum() or bch in "$_)]}\"'`":
                return False
            return True
        return True
    # Operators and delimiters that admit a regex on their right
    if ch in "=([{,;?!~*/%<>|&^:":
        return True
    return False


def _consume_regex_literal(expression: str, start: int) -> tuple[int, str] | None:
    """Consume a JS/TS regex literal ``/pattern/flags`` starting at ``start``.

    Respects ``\\`` escapes and ``[...]`` character classes.  Returns the new
    index and the consumed text if a valid regex literal is found; otherwise
    returns ``None`` so the caller can treat ``/`` as division.
    """
    n = len(expression)
    if expression[start] != "/":
        return None
    i = start + 1
    in_class = False
    escape = False
    while i < n:
        ch = expression[i]
        if escape:
            escape = False
            i += 1
            continue
        if ch == "\\":
            escape = True
            i += 1
            continue
        if in_class:
            if ch == "]":
                in_class = False
            i += 1
            continue
        if ch == "[":
            in_class = True
            i += 1
            continue
        if ch == "/":
            # Consume optional flags (gimsuvy)
            j = i + 1
            while j < n and expression[j].isalpha():
                j += 1
            return j, expression[start:j]
        if ch == "\n":
            break
        i += 1
    return None


def _strip_comments(expression: str) -> str:
    """Remove ``//`` line comments and ``/* ... */`` block comments while preserving strings.

    This is a small state-machine scanner so ``//`` or ``/*`` inside string or
    regex literals are not treated as comment starts.  It is used before Mumei
    normalization so trailing source comments do not leak into contract clauses.
    """
    result: list[str] = []
    i = 0
    n = len(expression)
    in_string: str | None = None
    escape = False
    while i < n:
        ch = expression[i]
        if in_string:
            result.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == in_string:
                in_string = None
            i += 1
            continue
        if ch in "\"'`":
            in_string = ch
            result.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n:
            if expression[i + 1] == "/":
                # Skip until end of line, but keep the newline itself.
                i += 2
                while i < n and expression[i] != "\n":
                    i += 1
                continue
            if expression[i + 1] == "*":
                # Skip block comment entirely.
                i += 2
                while i + 1 < n and not (expression[i] == "*" and expression[i + 1] == "/"):
                    i += 1
                i += 2
                continue
            # Could be a regex literal; only consume it when the context allows.
            if _is_regex_context("".join(result)):
                consumed = _consume_regex_literal(expression, i)
                if consumed is not None:
                    j, lit = consumed
                    result.append(lit)
                    i = j
                    continue
        result.append(ch)
        i += 1
    return "".join(result)


def _normalize_foreign_expression(expression: str) -> str:
    normalized = _strip_comments(expression).strip()
    normalized = normalized.replace("&&", "and").replace("||", "or")
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
