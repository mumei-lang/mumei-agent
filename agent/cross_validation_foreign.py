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

    def mask_literal(span: str) -> str:
        # Keep quote delimiters so the resulting source remains syntactically
        # valid for tree-sitter; only mask the literal contents.
        if len(span) <= 2:
            return span
        return span[0] + "".join("\n" if char == "\n" else " " for char in span[1:-1]) + span[-1]

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
            stripped.append(mask_literal(text[i:raw_end]))
            i = raw_end
            continue
        char = text[i]
        if char == '"':
            end = consume_string(i, char)
            stripped.append(mask_literal(text[i:end]))
            i = end
            continue
        if char == "'":
            end = consume_char_literal(i)
            if end:
                stripped.append(mask_literal(text[i:end]))
                i = end
                continue
        if char == "`":
            end = consume_string(i, char)
            stripped.append(mask_literal(text[i:end]))
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


def _filter_foreign_line_map(
    code: str, language: str, line_map: dict[str, int]
) -> dict[str, int]:
    """Drop test/placeholder entries that regex/tree-sitter line maps cannot distinguish.

    Go test entry points (``Test*``, ``Benchmark*``, ``Example*``, ``Fuzz*``) and the
    blank-identifier compile-check function ``func _()`` carry no verifiable contract.
    Rust functions annotated with ``#[test]`` or ``#[bench]`` are also skipped.
    """
    if language not in ("go", "rust") or not line_map:
        return line_map
    lines = code.splitlines()

    def _rust_line_is_test(line_number: int) -> bool:
        # 1-based line number from tree-sitter/regex map.
        idx = line_number - 1
        if idx < 0 or idx >= len(lines):
            return False
        for prev in range(idx - 1, max(-1, idx - 10), -1):
            stripped = re.sub(r"//.*", "", lines[prev]).strip()
            if not stripped:
                continue
            if stripped.startswith(("#[test]", "#[bench]")):
                return True
            # Stop scanning once we hit another item or non-attribute line.
            if not stripped.startswith("#"):
                return False
        return False

    filtered: dict[str, int] = {}
    for name, line in line_map.items():
        if language == "go":
            if name == "cross_validation_atom" or name.startswith(
                ("Test", "Benchmark", "Example", "Fuzz")
            ):
                continue
        if language == "rust" and _rust_line_is_test(line):
            continue
        filtered[name] = line
    return filtered


def _infer_foreign_source_line_map(code: str, language: str) -> dict[str, int]:
    language = _normalize_foreign_language(language)
    if language == "python":
        return _infer_python_source_line_map(code)
    # Prefer tree-sitter's full function extraction so test/blank filtering is
    # structural rather than regex/line based.
    if language in ("go", "rust"):
        ts_funcs = tree_sitter_extract.extract_contract_functions(
            code, language, _safe_identifier
        )
        if ts_funcs is not None:
            line_map: dict[str, int] = {}
            for fn in ts_funcs:
                if language == "go" and _is_go_test_name(fn.raw_name or fn.name):
                    continue
                if language == "rust" and (
                    "test" in fn.attributes or "bench" in fn.attributes
                ):
                    continue
                line_map.setdefault(fn.name, fn.line)
            return line_map
    if language in tree_sitter_extract.SUPPORTED_LANGUAGES:
        ts_line_map = tree_sitter_extract.function_line_map(
            code, language, _safe_identifier
        )
        if ts_line_map is not None:
            if language in ("go", "rust"):
                ts_line_map = _filter_foreign_line_map(code, language, ts_line_map)
            return ts_line_map
    if language == "rust":
        return _filter_foreign_line_map(
            code,
            "rust",
            _infer_regex_source_line_map(
                code,
                re.compile(
                    r"(?:pub(?:\([^)]*\))?\s+)?(?:unsafe\s+)?(?:async\s+)?fn\s+"
                    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*"
                    r"(?:<[^<>]*(?:<[^<>]*>[^<>]*)*>)?\s*"
                    r"\((?P<params>(?:[^()]|\([^)]*\))*)\)\s*"
                    r"(?P<ret>[^;{]*?)?\s*\{",
                    flags=re.DOTALL,
                ),
            ),
        )
    if language == "go":
        return _filter_foreign_line_map(
            code,
            "go",
            _infer_regex_source_line_map(
                code,
                re.compile(
                    r"func\s+(?:\([^)]*\)\s*)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\(",
                    flags=re.DOTALL,
                ),
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
    if not return_expr:
        return "true", return_expr
    # Emit mumei's canonical boolean literal spelling so the ensures clause
    # (``result == true``) lowers as a boolean equality rather than a comparison
    # against a fabricated ``True`` symbol.
    return f"result == {_canonical_boolean_literal(return_expr)}", return_expr


def _canonical_boolean_literal(expr: str) -> str:
    """Rewrite a bare Python ``True``/``False`` return to mumei's ``true``/``false``."""
    return {"True": "true", "False": "false"}.get(expr.strip(), expr)


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
    # JavaScript / TypeScript ``/`` and ``%`` with a zero divisor do not throw;
    # they return ``Infinity`` / ``NaN``.  Requiring a non-zero divisor for these
    # languages produces spurious counterexamples (#305).
    skip_divisors = language in {"typescript", "javascript"}
    for divisor in findings.divisors:
        if skip_divisors:
            continue
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
    # JavaScript / TypeScript division/modulo by zero is not an exception.
    if language not in {"typescript", "javascript"}:
        for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*(?:/|%)\s*([A-Za-z_][A-Za-z0-9_]*)", expression):
            divisor = match.group(2)
            if not semantic_safety.divisor_provably_nonzero(divisor, known_constants):
                requirements.append(f"{divisor} != 0")
    for match in re.finditer(
        r"\b(?P<container>[A-Za-z_][A-Za-z0-9_]*)\s*\[\s*(?P<index>[A-Za-z_][A-Za-z0-9_]*)\s*\](?!\s*[\w{])",
        expression,
    ):
        container = match.group("container")
        index = match.group("index")
        if container == "map":
            # ``map[K]V{...}`` is a Go map type/composite literal, not an index.
            continue
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
            _safe_identifier(value)
            for value in candidates
            if eligible_values is None or _safe_identifier(value) in eligible_values
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
    """Return the index of the next top-level ``{`` or ``;`` in a signature.

    Brackets inside the return type (``[u8; 32]``, ``Result<T, E>``,
    ``Fn() -> i32``) are tracked so a semicolon inside an array length or a
    generic argument is not mistaken for the end of the signature.
    """
    i = start
    bracket_depth = 0
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
        if ch in {"<", "(", "["}:
            bracket_depth += 1
        elif ch in {">", ")", "]"}:
            # Ignore ``->`` and ``=>`` arrow tokens.
            if ch == ">" and i > 0 and source[i - 1] in {"-", "="}:
                pass
            else:
                bracket_depth = max(0, bracket_depth - 1)
        elif ch in {"{", ";"} and bracket_depth == 0:
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
        return_type = _strip_rust_where_clause(source[i : body_start].strip())
    elif source[i] == "{":
        body_start = i
    elif source[i] == ";":
        body_start = i
    else:
        return None
    return params_text, return_type, body_start


def _has_rust_test_attribute(code: str, fn_start: int) -> bool:
    """True when the Rust function at ``fn_start`` is annotated with ``#[test]``/``#[bench]``.

    Also handles path-style attributes such as ``#[tokio::test]`` and
    ``#[tokio::test(flavor = "multi_thread")]``.
    """
    test_attr_re = re.compile(r"#\[(?:[\w_]+::)*(?:test|bench)\b")
    line_start = code.rfind("\n", 0, fn_start) + 1
    prev = line_start - 1
    while prev > 0 and code[prev] == "\n":
        prev -= 1
    if prev <= 0:
        return False
    # Walk backwards over consecutive attribute lines (e.g. #[test] #[should_panic]).
    while prev > 0:
        prev_line_start = code.rfind("\n", 0, prev) + 1
        prev_line = re.sub(r"//.*", "", code[prev_line_start : prev + 1]).strip()
        if not prev_line:
            break
        if test_attr_re.search(prev_line):
            return True
        if not prev_line.startswith("#"):
            break
        prev = prev_line_start - 1
        while prev > 0 and code[prev] == "\n":
            prev -= 1
    return False


def _infer_rust_contracts_tree_sitter(code: str) -> list[MumeiContractAtom] | None:
    """Use tree-sitter to extract Rust functions and signatures when available."""
    extracted = tree_sitter_extract.extract_contract_functions(code, "rust", _safe_identifier)
    if extracted is None:
        return None
    atoms: list[MumeiContractAtom] = []
    known_constants = semantic_safety.collect_declared_constants(code, "rust")
    for fn in extracted:
        if "test" in fn.attributes or "bench" in fn.attributes:
            continue
        return_type = _mumei_return_type(fn.return_type)
        params = _params_from_signature(fn.params_text)
        param_names = {p.name for p in params}
        param_types = {p.name: p.type for p in params}
        if not fn.body.strip():
            # Trait methods and external function declarations have no body.
            requires = "true"
            ensures = "true"
        else:
            return_expr = _normalize_foreign_expression(
                _last_expression(fn.body), known_constants, "rust"
            )
            safety_expr = _last_expression(_strip_go_rust_literals_and_comments(fn.body))
            requires = _rust_safety_requires_for_expression(safety_expr, known_constants)
            local_names = _local_variable_names(fn.body, "rust")
            ensures = _ensures_for_return_expression(return_expr, return_type, param_names, known_constants, local_names, param_types=param_types)
        atoms.append(
            MumeiContractAtom(
                name=fn.name,
                params=_params_from_signature(fn.params_text),
                return_type=return_type,
                requires=requires,
                ensures=ensures,
            )
        )
    return atoms


def _infer_rust_contracts(code: str) -> list[MumeiContractAtom]:
    ts_atoms = _infer_rust_contracts_tree_sitter(code)
    if ts_atoms is not None:
        return ts_atoms
    atoms: list[MumeiContractAtom] = []
    known_constants = semantic_safety.collect_declared_constants(code, "rust")
    name_pattern = re.compile(
        r"(?:pub(?:\([^)]*\))?\s+)?(?:unsafe\s+)?(?:async\s+)?fn\s+"
        r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*",
        flags=re.DOTALL,
    )
    for match in name_pattern.finditer(code):
        if _has_rust_test_attribute(code, match.start()):
            continue
        parsed = _rust_parse_signature(code, match.end())
        if parsed is None:
            continue
        params_text, return_type_text, body_start = parsed
        mumei_return_type = _mumei_return_type(return_type_text)
        # Trait methods and external function declarations terminate with `;`
        # and have no body to analyze, so emit them as trusted atoms.
        if body_start < len(code) and code[body_start] == ";":
            return_expr = ""
            requires = "true"
            ensures = "true"
        else:
            body = _balanced_brace_body(code, body_start)
            params = _params_from_signature(params_text)
            param_names = {p.name for p in params}
            param_types = {p.name: p.type for p in params}
            return_expr = _normalize_foreign_expression(
                _last_expression(body), known_constants, "rust"
            )
            safety_expr = _last_expression(
                _strip_go_rust_literals_and_comments(body)
            )
            requires = _rust_safety_requires_for_expression(
                safety_expr, known_constants
            )
            local_names = _local_variable_names(body, "rust")
            ensures = _ensures_for_return_expression(return_expr, mumei_return_type, param_names, known_constants, local_names, param_types=param_types)
        atoms.append(
            MumeiContractAtom(
                name=_safe_identifier(match.group("name")),
                params=_params_from_signature(params_text),
                return_type=mumei_return_type,
                requires=requires,
                ensures=ensures,
            )
        )
    return atoms


def _infer_solidity_contracts(code: str) -> list[MumeiContractAtom]:
    known_constants = semantic_safety.collect_declared_constants(code, "solidity")
    extracted = tree_sitter_extract.extract_contract_functions(
        code, "solidity", _safe_identifier
    )
    if extracted is not None:
        atoms: list[MumeiContractAtom] = []
        for fn in extracted:
            params, param_types = _solidity_params_from_signature(fn.params_text)
            param_names = {p.name for p in params}
            return_type = _mumei_return_type(
                fn.return_type,
                solidity_modifiers=True,
            )
            if fn.has_body:
                raw_return_expr = _raw_return_statement_expression(fn.body)
                return_expr = _normalize_foreign_expression(raw_return_expr, known_constants, "solidity")
                requires = _solidity_safety_requires_for_expression(
                    raw_return_expr,
                    param_types,
                    known_constants,
                )
                local_names = _local_variable_names(fn.body, "solidity")
                ensures = _ensures_for_return_expression(return_expr, return_type, param_names, known_constants, local_names)
            else:
                raw_return_expr = ""
                requires = "true"
                ensures = "true"
            atoms.append(
                MumeiContractAtom(
                    name=fn.name,
                    params=params,
                    return_type=return_type,
                    requires=requires,
                    ensures=ensures,
                )
            )
        return atoms
    # Regex fallback when tree-sitter / the grammar is unavailable.
    atoms: list[MumeiContractAtom] = []
    header = re.compile(
        r"function\s+(?P<name>[A-Za-z_$][\w$]*)\s*"
        r"\((?P<params>(?:[^()]|\([^)]*\))*)\)"
        r"(?P<attrs>[^{;]*?)(?P<delim>[{;])",
        flags=re.DOTALL,
    )
    for match in header.finditer(code):
        params, param_types = _solidity_params_from_signature(match.group("params"))
        param_names = {p.name for p in params}
        attrs = match.group("attrs") or ""
        returns_match = re.search(r"returns\s*\((?P<ret>[^)]*)\)", attrs)
        return_type = _mumei_return_type(
            returns_match.group("ret") if returns_match else None,
            solidity_modifiers=True,
        )
        is_interface = match.group("delim") == ";"
        if is_interface:
            raw_return_expr = ""
            return_expr = ""
            requires = "true"
            ensures = "true"
        else:
            body = _balanced_brace_body(code, match.end() - 1)
            raw_return_expr = _raw_return_statement_expression(body)
            return_expr = _normalize_foreign_expression(raw_return_expr, known_constants, "solidity")
            requires = _solidity_safety_requires_for_expression(
                raw_return_expr,
                param_types,
                known_constants,
            )
            local_names = _local_variable_names(body, "solidity")
            ensures = _ensures_for_return_expression(return_expr, return_type, param_names, known_constants, local_names)
        atoms.append(
            MumeiContractAtom(
                name=_safe_identifier(match.group("name")),
                params=params,
                return_type=return_type,
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


def _is_pointer_arithmetic_expression(expression: str, left: str, right: str) -> bool:
    """Return True when ``left + right`` is an argument to a pointer conversion."""
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
        if _is_pointer_arithmetic_expression(expression, left, right):
            continue
        requirements.extend(_i64_overflow_bounds(left, right))
    return requirements


def _infer_typescript_arrow_functions_with_tree_sitter(
    code: str,
    known_constants: dict[str, int],
) -> list[tuple[MumeiContractAtom, int]]:
    """Extract generic arrow-function contracts deterministically via tree-sitter."""
    parser = tree_sitter_extract._get_parser("typescript")
    if parser is None:
        return []
    source_bytes = code.encode("utf-8")
    try:
        tree = parser.parse(source_bytes)
    except Exception:
        return []
    root = tree.root_node
    function_ancestor_types = frozenset(
        {"arrow_function", "function_declaration", "function_expression", "method_definition"}
    )

    def _is_top_level(node) -> bool:
        n = node.parent
        while n is not None:
            if n.type in function_ancestor_types:
                return False
            n = n.parent
        return True

    def _text(node) -> str:
        return source_bytes[node.start_byte : node.end_byte].decode("utf-8", "replace")

    results: list[tuple[MumeiContractAtom, int]] = []
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "variable_declarator":
            arrow = node.child_by_field_name("value")
            if arrow is None or arrow.type != "arrow_function":
                stack.extend(reversed(node.children))
                continue
            if not _is_top_level(node):
                continue
            name_node = node.child_by_field_name("name")
            if name_node is None or name_node.type != "identifier":
                continue
            params_node = arrow.child_by_field_name("parameters")
            single_param_node = arrow.child_by_field_name("parameter")
            return_type_node = arrow.child_by_field_name("return_type")
            body_node = arrow.child_by_field_name("body")
            if body_node is None:
                continue
            if params_node is not None:
                params_text = _text(params_node).strip()[1:-1].strip()
            elif single_param_node is not None:
                params_text = _text(single_param_node).strip()
            else:
                params_text = ""
            return_type_text = (
                _text(return_type_node).lstrip(":").strip()
                if return_type_node is not None
                else "number"
            )
            if body_node.type == "statement_block":
                body = source_bytes[
                    body_node.start_byte + 1 : body_node.end_byte - 1
                ].decode("utf-8", "replace")
                is_expression_body = False
            else:
                body = _text(body_node)
                is_expression_body = True
            raw_return_expr = _typescript_raw_return_expression(body, is_expression_body)
            return_expr = _normalize_foreign_expression(raw_return_expr, known_constants, "typescript")
            return_type = _typescript_return_type(
                return_type_text or "number", raw_return_expr
            )
            raw_name = _text(name_node)
            start_char = len(
                source_bytes[: name_node.start_byte].decode("utf-8", "replace")
            )
            param_names = {p.name for p in _params_from_signature(params_text)}
            local_names = _local_variable_names(body, "typescript")
            atom = MumeiContractAtom(
                name=_safe_identifier(raw_name),
                params=_params_from_signature(params_text),
                return_type=return_type,
                requires=_safety_requires_for_expression(
                    raw_return_expr, "typescript", known_constants
                ),
                ensures=_ensures_for_return_expression(return_expr, return_type, param_names, known_constants, local_names),
            )
            results.append((atom, _safe_identifier(raw_name), start_char))
            continue
        stack.extend(reversed(node.children))
    return results


def _infer_typescript_contracts(code: str) -> list[MumeiContractAtom]:
    known_constants = semantic_safety.collect_declared_constants(code, "typescript")
    extracted = tree_sitter_extract.extract_contract_functions(
        code, "typescript", _safe_identifier
    )
    if extracted is not None:
        atoms: list[MumeiContractAtom] = []
        for fn in extracted:
            if not fn.is_top_level:
                continue
            if fn.has_body:
                raw_return_expr = _typescript_raw_return_expression(
                    fn.body, fn.is_expression_body
                )
                return_expr = _normalize_foreign_expression(raw_return_expr, known_constants, "typescript")
                return_type = _typescript_return_type(
                    (fn.return_type or "number").strip(), raw_return_expr
                )
                requires = _safety_requires_for_expression(
                    raw_return_expr, "typescript", known_constants
                )
                param_names = {p.name for p in _params_from_signature(fn.params_text)}
                local_names = _local_variable_names(fn.body, "typescript")
                ensures = _ensures_for_return_expression(return_expr, return_type, param_names, known_constants, local_names)
            else:
                requires = "true"
                ensures = "true"
            atoms.append(
                MumeiContractAtom(
                    name=fn.name,
                    params=_params_from_signature(fn.params_text),
                    return_type=return_type,
                    requires=requires,
                    ensures=ensures,
                )
            )
        return atoms
    # Regex fallback when tree-sitter / the grammar is unavailable.
    atoms: list[MumeiContractAtom] = []
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
    for pattern, is_expr_fn in patterns:
        for match in pattern.finditer(code):
            raw_body = match.group("body") or ""
            is_expression_body = is_expr_fn(raw_body)
            body_start = match.start("body")
            body = raw_body
            if raw_body.startswith("{"):
                body = _balanced_brace_body(code, body_start)
            elif body_start > 0 and code[body_start - 1] == "{":
                body = _balanced_brace_body(code, body_start - 1)
            raw_return_expr = _typescript_raw_return_expression(body, is_expression_body)
            return_expr = _normalize_foreign_expression(raw_return_expr, known_constants, "typescript")
            return_type = _typescript_return_type(
                match.group("ret") or "number", raw_return_expr
            )
            param_names = {p.name for p in _params_from_signature(match.group("params"))}
            local_names = _local_variable_names(body, "typescript")
            atoms.append(
                MumeiContractAtom(
                    name=_safe_identifier(match.group("name")),
                    params=_params_from_signature(match.group("params")),
                    return_type=return_type,
                    requires=_safety_requires_for_expression(
                        raw_return_expr, "typescript", known_constants
                    ),
                    ensures=_ensures_for_return_expression(return_expr, return_type, param_names, known_constants, local_names),
                )
            )
    return atoms


def _is_go_compiler_test_for_contracts(code: str) -> bool:
    """True for Go compiler test files that are not runnable user code."""
    for line in code.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        return stripped.startswith(("// errorcheck", "// runoutput", "// compiledir", "// asmcheck"))
    return False


def _infer_go_contracts_tree_sitter(code: str) -> list[MumeiContractAtom] | None:
    """Use tree-sitter to extract Go functions and signatures when available."""
    if _is_go_compiler_test_for_contracts(code):
        return []
    extracted = tree_sitter_extract.extract_contract_functions(code, "go", _safe_identifier)
    if extracted is None:
        return None
    atoms: list[MumeiContractAtom] = []
    known_constants = semantic_safety.collect_declared_constants(code, "go")
    for fn in extracted:
        if _is_go_test_name(fn.raw_name or fn.name):
            continue
        params = _params_from_signature(fn.params_text)
        go_param_types = _go_param_types(fn.params_text)
        nillable_names = _go_nillable_param_names(fn.params_text)
        raw_return_expr = _raw_return_statement_expression(fn.body, "go")
        return_type = _mumei_return_type(fn.return_type)
        if return_type in ("i64", "u64") and _is_go_string_literal(raw_return_expr):
            return_type = "string"
        if not fn.body.strip():
            # Assembly forward declarations and other external signatures have no body.
            requires = "true"
            ensures = "true"
        else:
            safety_exprs = _all_return_expressions(fn.body, "go")
            return_expr = _normalize_foreign_expression(raw_return_expr, known_constants, "go")
            param_names = {p.name for p in params}
            local_names = _local_variable_names(fn.body, "go")
            nillable_param_names = [param.name for param in params if param.name in nillable_names]
            requirements: list[str] = []
            for expr in safety_exprs:
                req = _go_safety_requires_for_expression(expr, nillable_param_names, known_constants)
                if req and req != "true":
                    requirements.extend(part.strip() for part in req.split("&&") if part.strip())
            requires = " && ".join(_dedupe_strings(requirements)) if requirements else "true"
            ensures = _ensures_for_return_expression(return_expr, return_type, param_names, known_constants, local_names, param_types=go_param_types)
        atoms.append(
            MumeiContractAtom(
                name=fn.name,
                params=params,
                return_type=return_type,
                requires=requires,
                ensures=ensures,
            )
        )
    return atoms


def _infer_go_contracts(code: str) -> list[MumeiContractAtom]:
    if _is_go_compiler_test_for_contracts(code):
        return []
    ts_atoms = _infer_go_contracts_tree_sitter(code)
    if ts_atoms is not None:
        return ts_atoms
    atoms: list[MumeiContractAtom] = []
    known_constants = semantic_safety.collect_declared_constants(code, "go")
    for name, params_text, return_type, body in _go_function_declarations(code):
        params = _params_from_signature(params_text)
        # Only params whose declared Go type is nillable may carry a `!= nil`
        # precondition; value types (e.g. `reflect.Value`) can never be nil, so
        # inferring one produces a false `refuted` verdict (#295).
        nillable_names = _go_nillable_param_names(params_text)
        go_param_types = _go_param_types(params_text)
        raw_return_expr = _raw_return_statement_expression(body, "go")
        return_expr = _normalize_foreign_expression(raw_return_expr, known_constants, "go")
        mumei_return_type = _mumei_return_type(return_type)
        if mumei_return_type in ("i64", "u64") and _is_go_string_literal(raw_return_expr):
            mumei_return_type = "string"
        param_names = {p.name for p in params}
        local_names = _local_variable_names(body, "go")
        nillable_param_names = [param.name for param in params if param.name in nillable_names]
        requirements: list[str] = []
        for expr in _all_return_expressions(body, "go"):
            req = _go_safety_requires_for_expression(expr, nillable_param_names, known_constants)
            if req and req != "true":
                requirements.extend(part.strip() for part in req.split("&&") if part.strip())
        requires = " && ".join(_dedupe_strings(requirements)) if requirements else "true"
        atoms.append(
            MumeiContractAtom(
                name=_safe_identifier(name),
                params=params,
                return_type=mumei_return_type,
                requires=requires,
                ensures=_ensures_for_return_expression(return_expr, mumei_return_type, param_names, known_constants, local_names, param_types=go_param_types),
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


def _is_go_test_name(name: str) -> bool:
    """True for Go identifiers that are the blank identifier or standard test entry points."""
    if name == "_":
        return True
    return name.startswith(("Test", "Benchmark", "Example", "Fuzz"))


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
        if _is_go_test_name(match.group("name")):
            continue
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


def _go_param_types(params_text: str) -> dict[str, str]:
    """Map Go parameter/receiver names to their raw Go type strings.

    Supports grouped declarations such as ``a, b *T`` by propagating the
    trailing type to all leading bare identifiers.
    """
    types: dict[str, str] = {}
    pending: list[str] = []
    for raw in _split_signature_params(params_text):
        raw = raw.strip()
        if not raw:
            continue
        match = re.fullmatch(r"([A-Za-z_]\w*)\s+(.+)", raw)
        if match:
            name, typ = match.group(1), match.group(2).strip()
            for pending_name in pending:
                types[pending_name] = typ
            types[name] = typ
            pending.clear()
        elif re.fullmatch(r"[A-Za-z_]\w*", raw):
            # Bare identifier whose type is declared in a later segment.
            pending.append(raw)
        else:
            pending.clear()
    return types


def _params_from_signature(params_text: str) -> list[ContractParam]:
    params: list[ContractParam] = []
    for index, raw in enumerate(_split_signature_params(params_text)):
        if not raw:
            continue
        # Skip Rust/TS method receivers such as `&mut self`, `&'a mut self`,
        # `self: &mut Self`, etc.
        if re.fullmatch(
            r"&?\s*(?:'[A-Za-z_][A-Za-z0-9_]*\s+)?(?:mut\s+)?self(?:\s*:\s*.+)?",
            raw.strip(),
            flags=re.IGNORECASE,
        ):
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
    # Strip a Rust lifetime qualifier such as ``'static`` in ``&'static str``.
    normalized = re.sub(r"^'[A-Za-z_][A-Za-z0-9_]*\s+", "", normalized)
    lowered = normalized.lower()
    if lowered in {"string", "str", "&str"} or lowered == "bytes":
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

# Type keywords recognized by ``_foreign_signature_type``.  Used to decide
# whether a spaced return-type declaration is ``Type name`` (Solidity) or
# ``name Type`` (Go named return value).
_MUMEI_KNOWN_TYPE_TOKENS = {
    "string", "str", "bool", "boolean", "float", "double", "f32", "f64",
    "uint", "usize", "u8", "u16", "u32", "u64",
    "int", "int8", "int16", "int32", "int64", "uintptr",
    "byte", "rune", "error",
    "void", "unit", "none", "nonetype",
}


def _is_go_string_literal(expression: str) -> bool:
    """True for a Go string literal (double-quoted or raw backtick)."""
    return bool(re.fullmatch(r'\s*(?:"(?:[^"\\]|\\.)*"|`[^`]*`)\s*', expression))


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
        # Solidity return declarations may name the return value (e.g. ``bool flag``).
        # Strip the name so it is not mistaken for an unknown type.
        if normalized and " " in normalized:
            normalized = normalized.split()[0]
    elif normalized and " " in normalized:
        # Go named return values are written ``name type`` (e.g. ``(b bool)``).
        # If the first token is not a recognizable type keyword, drop it and use
        # the remainder as the type.  This prevents ``result == false`` from being
        # rejected when the return type was mis-mapped to i64.
        tokens = normalized.split()
        if tokens[0].lower() not in _MUMEI_KNOWN_TYPE_TOKENS:
            normalized = " ".join(tokens[1:]).strip() or normalized
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

    Go parameter lists allow grouped names sharing a trailing type
    (``a, b *T``). The type applies to every leading identifier in the same
    group, including names from preceding comma-separated pieces.
    """
    names: set[str] = set()
    pending: list[str] = []
    for raw in _split_signature_params(params_text):
        raw = raw.strip()
        if not raw:
            continue
        # Remove commas so ``a, b *T`` becomes ``a b *T``.
        tokens = [t for t in raw.replace(",", " ").split() if t]
        if not tokens:
            continue
        type_start: int | None = None
        for i, token in enumerate(tokens):
            if token.startswith(("*", "[", "(", "chan", "<-", "func", "map")):
                type_start = i
                break
        if type_start is None and len(tokens) >= 2:
            # ``name type`` form; the last token is the type.
            type_start = len(tokens) - 1
        if type_start is None:
            # No type yet; keep identifiers as pending names.
            for token in tokens:
                pending.append(_safe_identifier(token))
            continue
        for token in tokens[:type_start]:
            pending.append(_safe_identifier(token))
        raw_type = " ".join(tokens[type_start:])
        if _go_type_is_nillable(raw_type):
            names.update(pending)
        pending = []
    return names


def _last_expression(body: str) -> str:
    stripped = body.strip().rstrip(";")
    if not stripped:
        return ""
    raw_lines = [line for line in stripped.splitlines()]
    # Compute brace depth at the start of each line so we ignore ``return``
    # statements and tail expressions that live inside nested closures or
    # blocks (e.g. Rust closure ``|x| { return false }`` inside a method call).
    # Count braces on a literal/comment-stripped copy so that ``{``/``}`` inside
    # string or char literals do not corrupt the depth tracking.
    masked_body = _strip_go_rust_literals_and_comments(stripped)
    masked_lines = [line for line in masked_body.splitlines()]
    start_depths: list[int] = []
    depth = 0
    for line in masked_lines:
        start_depths.append(depth)
        for ch in line:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
    lines = [line.strip() for line in raw_lines if line.strip()]
    for idx in range(len(raw_lines) - 1, -1, -1):
        line = raw_lines[idx].strip()
        if not line:
            continue
        # Skip anything nested inside a closure/block; only the function's
        # top-level (depth 0) tail or return expression is meaningful.
        if start_depths[idx] != 0:
            continue
        # If this line is the start of a multi-line method chain or call that
        # continues on the next line, do not treat it as a complete expression.
        next_idx = idx + 1
        while next_idx < len(masked_lines) and not masked_lines[next_idx].strip():
            next_idx += 1
        if next_idx < len(masked_lines):
            next_line = masked_lines[next_idx].strip()
            if re.match(r"^[.\(\)\->::]", next_line):
                continue
        candidate = _strip_comments(line).removeprefix("return ").strip().rstrip(";,").strip()
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
        # A bare string literal is usually a macro argument (e.g. Rust ``assert!``
        # message), not the function's tail expression.
        if isinstance(tree.body, ast.Constant) and isinstance(tree.body.value, str):
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


def _extract_return_expression(stripped: str, source: str, start: int) -> str:
    """Extract the expression after a ``return`` keyword.

    Balances ``()``, ``[]`` and ``{}`` and Solidity/TypeScript ternary ``?:``
    pairs so that multi-line returns and ternaries are captured in full.
    Also stops at ``case`` / ``default`` labels, which terminate a statement
    in Go ``switch`` / ``select`` blocks without an explicit semicolon.
    """
    depth = 0
    ternary_depth = 0
    i = start
    while i < len(stripped):
        ch = stripped[i]
        if ch in "([{":
            depth += 1
        elif ch in "])}" and depth > 0:
            depth -= 1
        elif ch == "?" and depth == 0:
            ternary_depth += 1
        elif ch == ":" and depth == 0 and ternary_depth > 0:
            ternary_depth -= 1
        elif (
            depth == 0
            and ternary_depth == 0
            and (i == 0 or not (stripped[i - 1].isalnum() or stripped[i - 1] == "_"))
            and re.match(r"(?:case|default)\b", stripped[i:])
        ):
            if _is_multi_value_return_expression(stripped[start:i].strip()):
                return ""
            return source[start:i].strip()
        elif ch in ";}" and depth == 0 and ternary_depth == 0:
            if _is_multi_value_return_expression(stripped[start:i].strip()):
                return ""
            return source[start:i].strip()
        i += 1
    if _is_multi_value_return_expression(stripped[start:].strip()):
        return ""
    return source[start:].strip()


def _raw_return_statement_expression(body: str, language: str = "") -> str:
    """Return the expression from the last ``return`` statement in ``body``.

    Stops at the end of the statement, balancing ``()`` ``[]`` ``{}`` and
    ternary ``?:`` pairs so that composite/struct literals and multi-line
    ternaries are captured in full instead of being truncated.

    If the body contains more than one ``return`` we cannot infer a single
    deterministic postcondition, so we return the empty string and let the
    caller default ``ensures`` to ``true``.

    Multi-value returns (e.g. Go ``return sum, carryOut != 0`` or Solidity
    ``return (a, b);``) cannot be expressed as a single ``result`` equality, so
    they are also normalised to the empty string.
    """
    body = _mask_nested_function_literals(body, language)
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

    return _extract_return_expression(stripped, body, returns[-1].end())


def _all_return_expressions(body: str, language: str = "") -> list[str]:
    """Return the expressions from every ``return`` statement in ``body``.

    Early returns may dereference values that the fall-through return does not,
    so a complete safety analysis must consider all exit expressions.
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
    return expressions


def _last_return_expression(body: str, language: str = "") -> str:
    """Return the expression from the last ``return`` statement, ignoring others.

    Used for safety-requirement extraction where the fall-through ``return`` is
    the only expression that can still dereference values.  Multi-value returns
    are still discarded because they cannot be expressed as a single expression.
    """
    body = _mask_nested_function_literals(body, language)
    stripped = _strip_go_rust_literals_and_comments(body)
    returns: list[re.Match[str]] = []
    for match in re.finditer(r"\breturn\b", stripped):
        end = match.end()
        if end < len(stripped) and (stripped[end].isalnum() or stripped[end] == "_"):
            continue
        returns.append(match)
    if not returns:
        return ""
    return _extract_return_expression(stripped, body, returns[-1].end())



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
    return _extract_return_expression(stripped_search, body, start)


def _typescript_return_type(type_text: str, return_expr: str = "") -> str:
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
    # No explicit return type; try to infer from the expression.
    if (not normalized or lowered in {"number", "any"}) and _looks_boolean(
        return_expr
    ):
        return "bool"
    return "i64"


def _looks_boolean(expression: str) -> bool:
    """Heuristically decide whether a TypeScript return expression is boolean."""
    if not expression:
        return False
    text = expression.strip()
    lowered = text.lower()
    if lowered in ("true", "false"):
        return True
    # String concatenation with string literals is not arithmetic and cannot be
    # lowered (e.g. Go ``netdir + "/cs"`` or ``net + "!" + host``).
    if re.search(r"['\"][^'\"]*['\"]\s*\+\s*|\s*\+\s*['\"][^'\"]*['\"]", text):
        return False
    # Array/object constructors are not boolean even if they contain comparisons.
    if re.search(
        r"\bArray\.from\s*\(|\.filter\s*\(|\.map\s*\(|\.reduce\s*\(|new\s+Array\s*\(",
        text,
    ):
        return False
    if re.search(r"\b(?:=>|return\s+\[|return\s+\{)", text):
        return False
    return bool(
        re.search(
            r"\b(?:typeof|in|instanceof)\b|(?:===|!==|==|!=|>=|<=|>|<|&&|\|\||\band\b|\bor\b|!)",
            text,
        )
    )


# Common JavaScript/TypeScript object/array properties and methods that are safe
# to pass through to Mumei without treating them as unresolved field accesses.
_KNOWN_PROPERTY_NAMES = frozenset({
    "map", "filter", "reduce", "forEach", "find", "some", "every", "includes",
    "indexOf", "lastIndexOf", "slice", "splice", "concat", "join", "split",
    "replace", "substring", "substr", "trim", "toLowerCase", "toUpperCase",
    "startsWith", "endsWith", "charAt", "charCodeAt", "fromCharCode", "length",
    "push", "pop", "shift", "unshift", "reverse", "sort", "keys", "values",
    "entries", "hasOwnProperty", "then", "catch", "finally", "toString",
    "valueOf", "parseInt", "parseFloat", "isNaN", "isFinite", "from",
})


def _local_variable_names(body: str, language: str) -> set[str]:
    """Return the set of identifiers declared as local variables in ``body``.

    This is a lightweight regex-based scan; tree-sitter extraction is preferred
    when available, but the fallback must not shell out or depend on external
    tools.  It is used to avoid lowering a reference to a local variable that
    Mumei cannot resolve into a contract atom.
    """
    language = _normalize_foreign_language(language)
    names: set[str] = set()
    if language == "go":
        # Short declarations ``x := ...`` may declare multiple names, e.g.
        # ``v, _ := strconv.ParseBool(...)``.  Capture every identifier on the
        # left-hand side before ``:=``.
        for match in re.finditer(r"\b([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s*:=", body):
            for name in re.findall(r"[A-Za-z_]\w*", match.group(1)):
                names.add(name)
        for match in re.finditer(r"\bvar\s+([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)", body):
            for name in re.findall(r"[A-Za-z_]\w*", match.group(1)):
                names.add(name)
    elif language == "rust":
        for match in re.finditer(r"\blet\s+(?:mut\s+)?([A-Za-z_]\w*)", body):
            names.add(match.group(1))
    elif language in {"typescript", "javascript"}:
        for match in re.finditer(r"\b(?:const|let|var)\s+([A-Za-z_]\w*)", body):
            names.add(match.group(1))
    elif language == "solidity":
        # Simple local declarations like ``uint x = ...;`` or ``T x = ...;``.
        for match in re.finditer(
            r"\b(?:uint|int|bytes|string|address|bool|mapping)\s+(?:[A-Za-z_]\w+\s+)?([A-Za-z_]\w*)\s*=",

            body,
        ):
            names.add(match.group(1))
    return names


def _is_expression_lowerable(
    expression: str,
    param_names: set[str] | None = None,
    known_constants: dict[str, int] | None = None,
    local_names: set[str] | None = None,
    param_types: dict[str, str] | None = None,
) -> bool:
    """Detect expressions that Mumei cannot lower.

    Without parameter/type information, every identifier is assumed lowerable.
    When parameter names are available, a token must either be a known constant,
    a parameter, a ``len_<param>`` length access, or a ``param_field`` method or
    known property call.  Ternaries, arrow functions and any unknown identifier
    cause a fallback to ``ensures true``.
    """
    if param_names is None and local_names is None:
        return True
    # JSX / TSX element literals cannot be lowered to a Mumei expression.
    if re.search(r"</|/>", expression):
        return False
    # String concatenation with string literals is not arithmetic and cannot be
    # lowered (e.g. Go ``netdir + "/cs"`` or ``net + "!" + host``).
    if re.search(r"['\"][^'\"]*['\"]\s*\+\s*|\s*\+\s*['\"][^'\"]*['\"]", expression):
        return False
    # Mumei arrays can only be indexed by integers.  Go map key access (e.g.
    # ``m["abc"]`` or ``m[s]`` where ``m`` is ``map[string]int``) cannot be
    # expressed as an ``ensures`` equality.
    if re.search(r"\[\s*(['\"])[^'\"]*\1\s*\]", expression):
        return False
    if param_types:
        for match in re.finditer(r"(?:\(\s*\*\s*)?([A-Za-z_]\w*)\s*\)?\s*\[\s*([A-Za-z_]\w*)\s*\]", expression):
            container = match.group(1)
            container_type = (param_types.get(container) or "").lstrip("*")
            if container_type.startswith("map["):
                return False
    no_strings = re.sub(r"'[^']*'|\"[^\"]*\"", "", expression)
    # Ternary and arrow-function bodies cannot be lowered into a single Mumei
    # equality over ``result``.
    if re.search(r"\?\s*[^?:]*\s*:\s*", no_strings):
        # Exclude object-type annotations of the form ``x is T`` which contain
        # no runtime ``?:`` ternary.
        if not re.search(r"\bis\s+[A-Za-z_]", no_strings):
            return False
    if "=>" in no_strings or "function" in no_strings.lower():
        return False
    # Object literals and method/field access on index/aggregate results cannot
    # be lowered.
    if re.search(r"\{[^}]*:", no_strings):
        return False
    if re.search(r"[\]\}]\s*\.", no_strings):
        return False
    allowed = {"true", "false", "null", "undefined", "and", "or", "not", "bit_and", "in", "len", "cap"}
    allowed.update(param_names)
    if known_constants:
        allowed.update(known_constants)
    # Array indexing in an ensures expression is only lowerable when both the
    # container and the index are known parameters/constants.  State-variable or
    # unknown arrays (e.g. Solidity ``_allTokens[index]``) cannot be lifted into a
    # Mumei equality.
    for match in re.finditer(
        r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\[\s*([^\[\]]*?)\s*\]",
        no_strings,
    ):
        container = match.group(1)
        index_expr = match.group(2).strip()
        if container not in allowed:
            return False
        if index_expr and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*|\d+", index_expr):
            return False
        if index_expr and index_expr not in allowed and not re.fullmatch(r"\d+", index_expr):
            return False
    # A bare, unknown single identifier is only lowerable when it is not a local
    # variable declared inside the same function body.  Globals/constants that
    # are not captured by ``known_constants`` are still allowed because Mumei can
    # model them as free variables.
    stripped = no_strings.strip()
    single = re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", stripped)
    if single:
        token = single.group(0)
        if token.startswith("len_") and token[4:] in param_names:
            pass
        elif token not in allowed:
            if local_names and token in local_names:
                return False
            # Otherwise the identifier is assumed to be a global/external name.
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", no_strings):
        if token in allowed:
            continue
        if local_names and token in local_names:
            return False
        if token.startswith("len_") and token[4:] in param_names:
            continue
        match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)_([A-Za-z_][A-Za-z0-9_]*)", token)
        if match:
            if match.group(1) in param_names:
                # Method calls such as ``fork_HashTreeRoot()`` are still callable.
                if re.search(rf"\b{re.escape(token)}\b\s*\(", no_strings):
                    continue
                if match.group(2) in _KNOWN_PROPERTY_NAMES:
                    continue
            # Any other ``unknown_something`` token is an unresolvable field/method
            # access and cannot be lowered.
            return False
        # Unknown bare identifiers used as function calls cannot be lowered.
        if re.search(rf"\b{re.escape(token)}\b\s*\(", no_strings):
            return False
        # Otherwise the identifier is assumed to be a global/external free variable.
    return True


def _ensures_for_return_expression(
    return_expr: str,
    return_type: str,
    param_names: set[str] | None = None,
    known_constants: dict[str, int] | None = None,
    local_names: set[str] | None = None,
    param_types: dict[str, str] | None = None,
) -> str:
    """Build a Mumei ``ensures`` clause, falling back to ``true`` for unverifiable types."""
    if not return_expr or return_type == "string":
        return "true"
    stripped = return_expr.strip().rstrip(",")
    # Boolean literals are only meaningful as the RHS of a boolean equality.
    # For non-bool return types (e.g. an inferred ``i64`` for ``SortExpr``) a
    # ``result == true`` clause lowers to a type error.  Likewise a string
    # literal as the apparent tail expression in a non-string function (e.g. a
    # nom parser combinator) is not the real return value.
    if return_type != "bool" and stripped in {"true", "false"}:
        return "true"
    if return_type != "string" and re.fullmatch(r'"[^"]*"', stripped):
        return "true"
    if not _is_expression_lowerable(return_expr, param_names, known_constants, local_names, param_types=param_types):
        return "true"
    # Mumei's vacuity-check lowerer only supports boolean equality with a bare
    # boolean variable or literal on the RHS (e.g. ``result == x`` or
    # ``result == true``).  Compound boolean expressions such as
    # ``year % 400 == 0 or ...`` fail with "Expected bool for ==".
    if return_type == "bool":
        if stripped in {"true", "false"}:
            return f"result == {stripped}"
        if param_names and stripped in param_names:
            # Only emit ``result == x`` when ``x`` is a boolean parameter;
            # otherwise the equality is a type error (e.g. ``&Expr`` is
            # mapped to ``i64`` but used as a bool RHS).
            if param_types and param_types.get(stripped) != "bool":
                return "true"
            return f"result == {stripped}"
        return "true"
    return f"result == {stripped}"


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


def _coerce_undefined_and_bang(expression: str) -> str:
    """Coerce ``undefined`` comparisons and rewrite prefix ``!`` for Mumei.

    Mumei has no ``undefined`` value and no unary ``!`` operator.  Comparisons
    against ``undefined`` are replaced with the corresponding boolean constant,
    and ``!x`` / ``!(expr)`` become ``(x == false)`` / ``((expr) == false)``,
    which Mumei can lower as boolean equalities.
    """
    normalized = re.sub(
        r"\b([A-Za-z_][A-Za-z0-9_]*)\s*(===|!==|==|!=)\s*undefined\b",
        lambda m: "true" if m.group(2) in ("!==", "!=") else "false",
        expression,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"\bundefined\s*(===|!==|==|!=)\s*([A-Za-z_][A-Za-z0-9_]*)\b",
        lambda m: "true" if m.group(1) in ("!==", "!=") else "false",
        normalized,
        flags=re.IGNORECASE,
    )
    return _rewrite_not(normalized)


def _rewrite_not(expression: str) -> str:
    """Rewrite unary ``!`` into an equality with ``false``.

    Skips ``!=`` / ``!==`` and leaves double negation untouched.  String
    literals are preserved so that exclamation marks inside strings are not
    rewritten.
    """
    result: list[str] = []
    i = 0
    n = len(expression)
    while i < n:
        ch = expression[i]
        if ch in '"\'':
            q = ch
            j = i + 1
            while j < n and expression[j] != q:
                if expression[j] == "\\":
                    j += 2
                else:
                    j += 1
            result.append(expression[i : j + 1])
            i = j + 1
            continue
        if ch == "!":
            j = i + 1
            while j < n and expression[j].isspace():
                j += 1
            if j < n and expression[j] == "=":
                # part of != or !==
                result.append("!")
                i += 1
                continue
            if j < n and expression[j] == "!":
                # leave double negation as-is
                result.append("!")
                i += 1
                continue
            if j < n and expression[j] == "(":
                k = j + 1
                depth = 1
                while k < n and depth > 0:
                    if expression[k] == "(":
                        depth += 1
                    elif expression[k] == ")":
                        depth -= 1
                    k += 1
                operand = expression[j:k]
                result.append(f"({operand} == false)")
                i = k
                continue
            k = j
            while k < n and (expression[k].isalnum() or expression[k] == "_"):
                k += 1
            identifier_end = k
            while k < n and expression[k].isspace():
                k += 1
            if k < n and expression[k] == "(":
                # ``!func(...)`` -> ``func(...) == false``
                paren_start = k
                depth = 1
                k += 1
                while k < n and depth > 0:
                    if expression[k] == "(":
                        depth += 1
                    elif expression[k] == ")":
                        depth -= 1
                    k += 1
                operand = expression[j:k]
                result.append(f"({operand} == false)")
                i = k
                continue
            operand = expression[j:identifier_end]
            result.append(f"({operand} == false)")
            i = identifier_end
            continue
        result.append(ch)
        i += 1
    return "".join(result)


def _coerce_typeof_and_string_literals(expression: str) -> str:
    """Replace ``typeof x === 'foo'`` and other string comparisons with ``true``.

    Mumei cannot lower the ``typeof`` operator or string literals, so these
    parts of a return expression are deterministically coerced to ``true``.
    The surrounding conjunction/disjunction (e.g. ``&& value !== null``) is
    preserved so that any non-string constraints remain verifiable.
    """
    # typeof x === 'object' / typeof x == 'object' / typeof x !== 'object' etc.
    normalized = re.sub(
        r"\btypeof\s+([A-Za-z_][A-Za-z0-9_]*)\s*(==|!=)\s*['\"]([^'\"]*)['\"]",
        "true",
        expression,
    )
    # Coerce any remaining equality against a string literal to ``true``.
    normalized = re.sub(
        r"\b([A-Za-z_][A-Za-z0-9_]*)\s*==\s*['\"]([^'\"]*)['\"]",
        "true",
        normalized,
    )
    return normalized


def _simplify_boolean_literals(expression: str) -> str:
    """Fold trivial ``true``/``false`` sub-expressions."""
    changed = True
    result = expression
    while changed:
        changed = False
        # true and X -> X, X and true -> X
        m = re.fullmatch(r"true\s+and\s+(.+)", result, re.IGNORECASE)
        if m:
            result = m.group(1).strip()
            changed = True
            continue
        m = re.fullmatch(r"(.+?)\s+and\s+true", result, re.IGNORECASE)
        if m and not re.search(r"\bor\b", m.group(1), re.IGNORECASE):
            result = m.group(1).strip()
            changed = True
            continue
        # true or X -> true, X or true -> true
        m = re.fullmatch(r"true\s+or\s+.+|.+\s+or\s+true", result, re.IGNORECASE)
        if m:
            result = "true"
            changed = True
            continue
        # false and X -> false, X and false -> false
        m = re.fullmatch(r"false\s+and\s+.+|.+\s+and\s+false", result, re.IGNORECASE)
        if m:
            result = "false"
            changed = True
            continue
    return result


def _parenthesize_boolean_expression(expression: str) -> str:
    """Wrap expressions containing boolean/comparison operators in parentheses.

    Without parentheses Mumei parses ``result == i > i0`` left-to-right and
    fails to lower the clause. Wrapping ensures the right-hand side is treated
    as a single boolean term.
    """
    text = expression.strip()
    if not text:
        return text
    # If the expression is already a single parenthesised group, leave it.
    if text.startswith("(") and text.endswith(")"):
        depth = 0
        valid = True
        for i, ch in enumerate(text):
            if ch in "([{":
                depth += 1
            elif ch in "])}" and depth > 0:
                depth -= 1
            if depth == 0 and i < len(text) - 1:
                valid = False
                break
        if valid and depth == 0:
            return text
    # Temporarily hide bit shifts so ``<<`` / ``>>`` are not treated as
    # comparison operators.
    placeholders = {"<<": " __LSHIFT__ ", ">>": " __RSHIFT__ "}
    probe = text
    for op, placeholder in placeholders.items():
        probe = probe.replace(op, placeholder)
    if re.search(r"\b(?:and|or)\b|>=|<=|==|!=|[<>]", probe):
        return f"({text})"
    return text


def _normalize_bit_shifts(expression: str) -> str:
    """Rewrite ``<<`` / ``>>`` to multiplication/division by powers of two.

    Mumei does not have a bit-shift operator, so ``1 << n`` is parsed as two
    ``<`` comparisons and fails to lower. Rewriting to ``(1 * 2**n)`` keeps the
    arithmetic intent while staying within the subset Mumei can verify.
    """
    normalized = re.sub(
        r"\b(\w+)\s*<<\s*(\w+)\b",
        r"(\1 * 2**\2)",
        expression,
    )
    normalized = re.sub(
        r"\b(\w+)\s*>>\s*(\w+)\b",
        r"(\1 / 2**\2)",
        normalized,
    )
    return normalized


def _maybe_unparenthesize(expression: str) -> str:
    """Strip a single pair of surrounding parentheses if the whole expr is grouped."""
    text = expression.strip()
    if not (text.startswith("(") and text.endswith(")")):
        return text
    depth = 0
    for i, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if depth == 0 and i < len(text) - 1:
            return text
    return text[1:-1]


def _bitwise_operand_left(expression: str, pos: int) -> tuple[int, int] | None:
    """Return the (start, end) range of the operand immediately left of ``pos``."""
    i = pos - 1
    while i >= 0 and expression[i].isspace():
        i -= 1
    if i < 0:
        return None
    end = i + 1
    ch = expression[i]
    if ch == ")":
        depth = 1
        i -= 1
        while i >= 0 and depth > 0:
            if expression[i] == ")":
                depth += 1
            elif expression[i] == "(":
                depth -= 1
            i -= 1
        # i now points to the char before the matching '('
        start_paren = i + 1  # position of '('
        # If the group is preceded by an identifier, it's a function call.
        while i >= 0 and expression[i].isspace():
            i -= 1
        j = i
        while j >= 0 and (expression[j].isalnum() or expression[j] == "_"):
            j -= 1
        if j < i:
            start = j + 1
        else:
            start = start_paren
        return (start, end)
    if ch.isalnum() or ch == "_":
        while i >= 0 and (expression[i].isalnum() or expression[i] == "_"):
            i -= 1
        return (i + 1, end)
    return None


def _bitwise_operand_right(expression: str, pos: int) -> tuple[int, int] | None:
    """Return the (start, end) range of the operand immediately right of ``pos``."""
    n = len(expression)
    i = pos + 1
    while i < n and expression[i].isspace():
        i += 1
    if i >= n:
        return None
    start = i
    ch = expression[i]
    if ch == "(":
        depth = 1
        i += 1
        while i < n and depth > 0:
            if expression[i] == "(":
                depth += 1
            elif expression[i] == ")":
                depth -= 1
            i += 1
        return (start, i)
    if ch.isalnum() or ch == "_":
        while i < n and (expression[i].isalnum() or expression[i] == "_"):
            i += 1
        # If followed by '(', it's a function call; consume the arguments.
        if i < n and expression[i].isspace():
            j = i
            while j < n and expression[j].isspace():
                j += 1
            if j < n and expression[j] == "(":
                i = j
        if i < n and expression[i] == "(":
            depth = 1
            i += 1
            while i < n and depth > 0:
                if expression[i] == "(":
                    depth += 1
                elif expression[i] == ")":
                    depth -= 1
                i += 1
        return (start, i)
    if ch.isdigit():
        while i < n and (expression[i].isalnum() or expression[i] == "_"):
            i += 1
        return (start, i)
    return None


def _find_bitwise_and(expression: str, start: int = 0) -> int | None:
    """Find the next bare ``&`` operator not inside a string or parentheses."""
    i = start
    n = len(expression)
    in_string: str | None = None
    paren_depth = 0
    while i < n:
        ch = expression[i]
        if in_string:
            if ch == in_string and (i == 0 or expression[i - 1] != "\\"):
                in_string = None
            i += 1
            continue
        if ch in '"\'':
            in_string = ch
            i += 1
            continue
        if ch in "([{":
            paren_depth += 1
            i += 1
            continue
        if ch in ")]}" and paren_depth > 0:
            paren_depth -= 1
            i += 1
            continue
        if ch == "&" and paren_depth == 0:
            # Avoid matching '&&' (already replaced earlier) and '&='.
            if (i + 1 < n and expression[i + 1] == "&") or (
                i + 1 < n and expression[i + 1] == "=" or
                (i > 0 and expression[i - 1] == "&")
            ):
                pass
            else:
                return i
        i += 1
    return None


def _normalize_bitwise_and(expression: str) -> str:
    """Rewrite ``a & b`` to ``bit_and(a, b)`` for Mumei lowering.

    Handles chains such as ``a & b & c`` by iterating left-to-right and allows
    function-call and parenthesised operands, e.g. ``bit_and(a, b) & c`` or
    ``(a & b) & c``.
    """
    result = expression
    i = 0
    while True:
        pos = _find_bitwise_and(result, i)
        if pos is None:
            break
        left = _bitwise_operand_left(result, pos)
        right = _bitwise_operand_right(result, pos)
        if left is None or right is None:
            i = pos + 1
            continue
        left_text = result[left[0] : left[1]]
        right_text = result[right[0] : right[1]]
        # Recursively rewrite any nested & inside operand parentheses.
        left_text = _normalize_bitwise_and(_maybe_unparenthesize(left_text))
        right_text = _normalize_bitwise_and(_maybe_unparenthesize(right_text))
        replacement = f"bit_and({left_text}, {right_text})"
        result = result[: left[0]] + replacement + result[right[1] :]
        i = left[0] + len(replacement)
    return result


def _inline_known_constants(
    expression: str,
    known_constants: dict[str, int] | None,
) -> str:
    """Replace declared constant names with integer values so Mumei can lower them."""
    if not known_constants:
        return expression
    for name, value in known_constants.items():
        expression = re.sub(rf"\b{re.escape(name)}\b", str(value), expression)
    return expression


def _inline_character_literals(
    expression: str,
    language: str,
) -> str:
    """Replace Go/Rust character literals with integer constants.

    Mumei has no character-literal syntax, so ``'A'`` is converted to ``65``.
    Only single-quoted literals outside double-quoted strings are rewritten;
    strings are left untouched.
    """
    if language not in {"go", "rust"}:
        return expression
    result: list[str] = []
    i = 0
    n = len(expression)
    in_double = False
    double_escape = False
    while i < n:
        ch = expression[i]
        if in_double:
            result.append(ch)
            if double_escape:
                double_escape = False
            elif ch == "\\":
                double_escape = True
            elif ch == '"':
                in_double = False
            i += 1
            continue
        if ch == '"':
            in_double = True
            result.append(ch)
            i += 1
            continue
        if ch == "'":
            j = i + 1
            char_escape = False
            while j < n:
                c = expression[j]
                if char_escape:
                    char_escape = False
                elif c == "\\":
                    char_escape = True
                elif c == "'":
                    break
                j += 1
            token = expression[i : j + 1]
            try:
                value = ast.literal_eval(token)
                if isinstance(value, str) and len(value) == 1:
                    result.append(str(ord(value)))
                else:
                    result.append(token)
            except (ValueError, SyntaxError):
                result.append(token)
            i = j + 1
            continue
        result.append(ch)
        i += 1
    return "".join(result)


def _normalize_foreign_expression(
    expression: str,
    known_constants: dict[str, int] | None = None,
    language: str = "",
) -> str:
    normalized = _strip_comments(expression).strip()
    normalized = normalized.replace("&&", "and").replace("||", "or")
    normalized = normalized.replace("===", "==").replace("!==", "!=")
    normalized = re.sub(r"\b([A-Za-z_][A-Za-z0-9_]*)\.length\b", r"len_\1", normalized)
    normalized = re.sub(r"\b([A-Za-z_][A-Za-z0-9_]*)!?\.", r"\1_", normalized)
    normalized = _normalize_bitwise_and(normalized)
    normalized = _inline_known_constants(normalized, known_constants)
    normalized = _coerce_typeof_and_string_literals(normalized)
    normalized = _coerce_undefined_and_bang(normalized)
    normalized = _simplify_boolean_literals(normalized)
    normalized = _normalize_bit_shifts(normalized)
    normalized = _inline_character_literals(normalized, _normalize_foreign_language(language))
    normalized = _parenthesize_boolean_expression(normalized)
    return normalized


def _mask_go_function_literals(body: str) -> str:
    """Replace nested Go function literal bodies with spaces.

    Uses a stripped copy of ``body`` (string/comment contents replaced with
    spaces) to locate literal boundaries, then applies the same ranges to the
    original text so positions remain valid.  This prevents ``return``
    statements inside closures from leaking into the outer function's safety
    or contract inference.
    """
    stripped = _strip_go_rust_literals_and_comments(body)
    mask = [False] * len(body)

    def _body_range(start: int) -> tuple[int, int] | None:
        """Return the [start, end) range of the function literal body."""
        paren = 0
        bracket = 0
        i = start
        n = len(stripped)
        while i < n:
            ch = stripped[i]
            if ch == "(":
                paren += 1
            elif ch == ")":
                paren -= 1
            elif ch == "[":
                bracket += 1
            elif ch == "]":
                bracket -= 1
            elif ch == "{" and paren == 0 and bracket == 0:
                # Skip ``struct`` / ``interface`` type blocks, which can appear
                # as result types or embedded composite types.
                prev_start = i - 1
                while prev_start >= 0 and stripped[prev_start].isspace():
                    prev_start -= 1
                while prev_start >= 0 and (
                    stripped[prev_start].isalnum() or stripped[prev_start] == "_"
                ):
                    prev_start -= 1
                prev_word = stripped[prev_start + 1 : i].strip()
                if prev_word in {"struct", "interface"}:
                    depth = 1
                    i += 1
                    while i < n and depth > 0:
                        if stripped[i] == "{":
                            depth += 1
                        elif stripped[i] == "}":
                            depth -= 1
                        i += 1
                    continue
                # ``{`` is the function body; find its matching ``}``.
                depth = 1
                j = i + 1
                while j < n and depth > 0:
                    if stripped[j] == "{":
                        depth += 1
                    elif stripped[j] == "}":
                        depth -= 1
                    j += 1
                return i, j
            i += 1
        return None

    for match in re.finditer(r"\bfunc\b", stripped):
        start = match.start()
        # Only function literals inside this body are nested.  A bare ``func``
        # immediately followed by an identifier (a declaration) cannot occur
        # inside another function body.
        j = match.end()
        while j < len(stripped) and stripped[j].isspace():
            j += 1
        if j < len(stripped) and (stripped[j].isalnum() or stripped[j] == "_"):
            continue
        rng = _body_range(start)
        if rng is not None:
            for k in range(rng[0], rng[1]):
                if not stripped[k].isspace() or stripped[k] == "\n":
                    mask[k] = True

    return "".join(" " if mask[i] and body[i] not in "\n" else body[i] for i in range(len(body)))


def _mask_typescript_function_literals(body: str) -> str:
    """Mask bodies of nested TypeScript/JavaScript function and arrow literals."""
    tree, source_bytes = tree_sitter_extract._parse(body, "typescript")
    if tree is None or source_bytes is None:
        return body
    mask = bytearray(source_bytes)
    node_types = tree_sitter_extract._VALUE_FUNCTION_NODE_TYPES | {
        "function_expression",
        "function_declaration",
        "method_definition",
    }

    def _walk(node):
        if node.type in node_types:
            for i in range(node.start_byte, node.end_byte):
                if source_bytes[i] != ord("\n"):
                    mask[i] = ord(" ")
        for child in node.children:
            _walk(child)

    _walk(tree.root_node)
    return mask.decode("utf-8", "replace")


def _mask_nested_function_literals(body: str, language: str) -> str:
    """Mask bodies of nested function literals for the given language."""
    language = _normalize_foreign_language(language)
    if language == "go":
        return _mask_go_function_literals(body)
    if language in {"typescript", "javascript"}:
        return _mask_typescript_function_literals(body)
    return body


_MUMEI_RESERVED_IDENTIFIERS = {"call"}


def _safe_identifier(value: str) -> str:
    safe = re.sub(r"\W+", "_", value.strip())
    safe = safe.strip("_")
    if not safe:
        return "cross_validation_atom"
    if safe[0].isdigit():
        return f"atom_{safe}"
    if safe in _MUMEI_RESERVED_IDENTIFIERS:
        return f"{safe}_"
    return safe
