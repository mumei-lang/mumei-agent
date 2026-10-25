from __future__ import annotations

import argparse
import ast
from collections import Counter
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Iterable

from agent import tree_sitter_extract


_EXTENSIONS = {".py": "python", ".rs": "rust"}
_OBSERVATION_KINDS = ("example", "relation", "rejects", "property")
_MIN_I64 = -(2**63)
_MAX_I64 = 2**63 - 1
_BINARY_OPERATORS = {
    "+": 4,
    "-": 4,
    "*": 5,
    "==": 3,
    "!=": 3,
    "<": 3,
    "<=": 3,
    ">": 3,
    ">=": 3,
    "&&": 2,
    "||": 1,
    "and": 2,
    "or": 1,
}
_UNSUPPORTED_BINARY_OPERATORS = {
    "/": 5,
    "%": 5,
}
_PYTHON_BINARY_OPERATORS = {
    ast.Add: "+",
    ast.Sub: "-",
    ast.Mult: "*",
}
_PYTHON_COMPARISON_OPERATORS = {
    ast.Eq: "==",
    ast.NotEq: "!=",
    ast.Lt: "<",
    ast.LtE: "<=",
    ast.Gt: ">",
    ast.GtE: ">=",
}
_UNITTEST_ASSERTIONS = {
    "assertNotEqual": "!=",
    "assertLess": "<",
    "assertLessEqual": "<=",
    "assertGreater": ">",
    "assertGreaterEqual": ">=",
}


class HarvestInputError(ValueError):
    pass


@dataclass(frozen=True)
class _Definition:
    name: str
    params: tuple[str, ...] | None
    file: str | None
    line: int | None
    receiver: bool = False
    language: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "params": list(self.params) if self.params is not None else None,
            "file": self.file,
            "line": self.line,
        }


@dataclass(frozen=True)
class _Test:
    name: str
    file: str
    language: str
    source: str
    node: Any
    should_panic: bool = False
    not_run: bool = False
    python_imports: frozenset[str] = frozenset()
    python_imported_names: frozenset[str] = frozenset()
    python_module_aliases: tuple[tuple[str, str], ...] = ()
    python_name_aliases: tuple[tuple[str, str], ...] = ()
    property_test: bool = False
    property_variables: tuple[dict[str, Any], ...] = ()
    property_assumptions: tuple[str, ...] = ()
    property_skip_reason: str | None = None


@dataclass(frozen=True)
class _Expr:
    kind: str
    value: Any = None
    children: tuple[_Expr, ...] = ()


@dataclass(frozen=True)
class _Token:
    kind: str
    text: str


class _ExpressionError(ValueError):
    pass


class _OutOfRangeLiteralError(_ExpressionError):
    pass


def _walk(node: Any) -> Iterable[Any]:
    yield node
    for child in getattr(node, "children", ()):
        yield from _walk(child)


def _python_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _python_target_name(
    node: ast.expr, imported_roots: frozenset[str]
) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        if _python_root_name(node) in imported_roots:
            return node.attr
    return None


def _python_nested_write_names(
    scope_nodes: tuple[ast.AST, ...], declared_names: set[str]
) -> Iterable[str]:
    scope_root = scope_nodes[0] if scope_nodes else None
    for scope_node in scope_nodes:
        if isinstance(scope_node, ast.Name) and isinstance(
            scope_node.ctx, (ast.Store, ast.Del)
        ):
            yield scope_node.id
        elif (
            scope_node is not scope_root
            and isinstance(
                scope_node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            )
            and scope_node.name in declared_names
        ):
            yield scope_node.name
        elif isinstance(scope_node, ast.Import):
            yield from (
                alias.asname or alias.name.split(".", 1)[0]
                for alias in scope_node.names
            )
        elif isinstance(scope_node, ast.ImportFrom):
            yield from (
                alias.asname or alias.name
                for alias in scope_node.names
                if alias.name != "*"
            )
        elif isinstance(scope_node, ast.ExceptHandler) and scope_node.name:
            yield scope_node.name
        elif isinstance(scope_node, ast.MatchAs) and scope_node.name:
            yield scope_node.name


def _python_scope_write_nodes(node: ast.AST) -> Iterable[ast.AST]:
    yield node
    for child in ast.iter_child_nodes(node):
        if isinstance(
            child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        ):
            yield child
        else:
            yield from _python_scope_write_nodes(child)


def _python_test_writes(test_node: ast.AST) -> set[str]:
    writes: set[str] = set()
    scope_types = (
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.ClassDef,
        ast.Lambda,
    )
    for node in _python_scope_nodes(test_node):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            writes.add(node.id)
        elif isinstance(node, ast.arg):
            writes.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            writes.add(node.name)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            writes.add(node.name)
        elif isinstance(node, ast.MatchAs) and node.name:
            writes.add(node.name)

    def nested_writes(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, scope_types):
                scope_nodes = tuple(_python_scope_write_nodes(child))
                declared_names = {
                    name
                    for scope_node in scope_nodes
                    if isinstance(scope_node, (ast.Global, ast.Nonlocal))
                    for name in scope_node.names
                }
                writes.update(
                    name
                    for name in _python_nested_write_names(
                        scope_nodes, declared_names
                    )
                    if name in declared_names
                )
            nested_writes(child)

    nested_writes(test_node)
    return writes


def _python_import_roots(
    tree: ast.Module, test_node: ast.AST, module_names: set[str]
) -> frozenset[str]:
    roots: set[str] = set()
    nodes = list(_python_scope_nodes(tree))
    nodes.extend(_python_scope_nodes(test_node))
    for node in nodes:
        if isinstance(node, ast.Import):
            roots.update(alias.asname or alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            roots.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name in module_names
            )
    return frozenset(roots - _python_test_writes(test_node))


def _python_imported_names(tree: ast.Module, test_node: ast.AST) -> frozenset[str]:
    names: set[str] = set()
    nodes = list(_python_scope_nodes(tree))
    nodes.extend(_python_scope_nodes(test_node))
    for node in nodes:
        if isinstance(node, ast.Import):
            names.update(
                alias.asname or alias.name.split(".", 1)[0] for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names)
    return frozenset(names - _python_test_writes(test_node))


def _python_import_aliases(
    tree: ast.Module, test_node: ast.AST | None = None
) -> tuple[dict[str, str], dict[str, str]]:
    modules: dict[str, str] = {}
    names: dict[str, str] = {}
    nodes = list(_python_scope_nodes(tree))
    if test_node is not None:
        nodes.extend(_python_scope_nodes(test_node))
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules[alias.asname or alias.name.split(".", 1)[0]] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                names[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return modules, names


def _python_decorator_name(
    decorator: ast.expr,
    modules: dict[str, str],
    names: dict[str, str],
) -> str:
    if isinstance(decorator, ast.Call):
        decorator = decorator.func
    if isinstance(decorator, ast.Name):
        return names.get(decorator.id, modules.get(decorator.id, decorator.id))
    if isinstance(decorator, ast.Attribute):
        parent = _python_decorator_name(decorator.value, modules, names)
        return f"{parent}.{decorator.attr}" if parent else decorator.attr
    return ""


_SKIP_DECORATORS = {
    "pytest.mark.skip",
    "pytest.mark.skipif",
    "pytest.mark.xfail",
    "unittest.skip",
    "unittest.skipIf",
    "unittest.skipUnless",
    "unittest.expectedFailure",
}

_PYTHON_TERMINATING_CALLS = {
    "pytest.fail",
    "pytest.skip",
    "pytest.exit",
    "self.fail",
    "self.skipTest",
    "sys.exit",
    "os._exit",
}


def _python_resolved_name(
    node: ast.expr, modules: dict[str, str], names: dict[str, str]
) -> str:
    if isinstance(node, ast.Name):
        return names.get(node.id, modules.get(node.id, node.id))
    if isinstance(node, ast.Attribute):
        parent = _python_resolved_name(node.value, modules, names)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _python_is_hypothesis_call(node: ast.expr, test: _Test) -> bool:
    if not test.property_test:
        return False
    resolved = _python_resolved_name(
        node,
        dict(test.python_module_aliases),
        dict(test.python_name_aliases),
    )
    return resolved.startswith("hypothesis.")


def _python_statement_terminates(statement: ast.stmt, test: _Test) -> bool:
    if not isinstance(statement, ast.Expr) or not isinstance(
        statement.value, ast.Call
    ):
        return False
    return (
        _python_resolved_name(
            statement.value.func,
            dict(test.python_module_aliases),
            dict(test.python_name_aliases),
        )
        in _PYTHON_TERMINATING_CALLS
    )


def _python_is_skipped(
    decorators: list[ast.expr], modules: dict[str, str], names: dict[str, str]
) -> bool:
    for decorator in decorators:
        name = _python_decorator_name(decorator, modules, names)
        if name not in _SKIP_DECORATORS:
            continue
        if name in {"pytest.mark.skipif", "unittest.skipIf", "unittest.skipUnless"}:
            condition: ast.expr | None = None
            if isinstance(decorator, ast.Call):
                condition = decorator.args[0] if decorator.args else next(
                    (
                        keyword.value
                        for keyword in decorator.keywords
                        if keyword.arg == "condition"
                    ),
                    None,
                )
            if not isinstance(condition, ast.Constant) or not isinstance(
                condition.value, bool
            ):
                return True
            if name == "unittest.skipUnless":
                if not condition.value:
                    return True
            elif condition.value:
                return True
        else:
            return True
    return False


def _python_definition_line(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    return max((decorator.lineno for decorator in node.decorator_list), default=node.lineno - 1) + 1


def _python_expr(
    node: ast.expr, imported_roots: frozenset[str] = frozenset()
) -> _Expr:
    if isinstance(node, ast.Constant) and (
        isinstance(node.value, bool) or isinstance(node.value, int)
    ):
        return _Expr("literal", node.value)
    if isinstance(node, ast.Name):
        return _Expr("name", node.id)
    if isinstance(node, ast.Call):
        name = _python_target_name(node.func, imported_roots)
        return _Expr(
            "call",
            (name, bool(node.keywords)),
            tuple(_python_expr(arg, imported_roots) for arg in node.args),
        )
    if isinstance(node, ast.UnaryOp):
        op = "not" if isinstance(node.op, ast.Not) else (
            "-" if isinstance(node.op, ast.USub) else (
                "+" if isinstance(node.op, ast.UAdd) else None
            )
        )
        return _Expr(
            "unary",
            op,
            (_python_expr(node.operand, imported_roots),),
        )
    if isinstance(node, ast.BinOp):
        op = _PYTHON_BINARY_OPERATORS.get(type(node.op))
        return _Expr(
            "binary",
            op,
            (
                _python_expr(node.left, imported_roots),
                _python_expr(node.right, imported_roots),
            ),
        )
    if isinstance(node, ast.BoolOp):
        op = "and" if isinstance(node.op, ast.And) else (
            "or" if isinstance(node.op, ast.Or) else None
        )
        return _Expr(
            "boolean",
            op,
            tuple(_python_expr(value, imported_roots) for value in node.values),
        )
    if isinstance(node, ast.Compare):
        operators = tuple(
            _PYTHON_COMPARISON_OPERATORS.get(type(op)) for op in node.ops
        )
        return _Expr(
            "compare",
            operators,
            (
                _python_expr(node.left, imported_roots),
                *(
                    _python_expr(value, imported_roots)
                    for value in node.comparators
                ),
            ),
        )
    return _Expr(
        "unsupported",
        children=tuple(
            _python_expr(child, imported_roots)
            for child in ast.iter_child_nodes(node)
            if isinstance(child, ast.expr)
        ),
    )


def _python_scope_nodes(node: ast.AST) -> Iterable[ast.AST]:
    yield node
    for child in ast.iter_child_nodes(node):
        if isinstance(
            child,
            (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda),
        ):
            continue
        yield from _python_scope_nodes(child)


def _python_tests(tree: ast.Module) -> list[_Test]:
    tests: list[_Test] = []
    modules, names = _python_import_aliases(tree)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                tests.append(
                    _Test(
                        node.name,
                        "",
                        "python",
                        "",
                        node,
                        not_run=_python_is_skipped(
                            node.decorator_list, modules, names
                        ),
                    )
                )
        elif isinstance(node, ast.ClassDef):
            is_test_class = node.name.startswith("Test") or any(
                _python_base_name(base).endswith("TestCase") for base in node.bases
            )
            if not is_test_class:
                continue
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if child.name.startswith("test_"):
                        tests.append(
                            _Test(
                                child.name,
                                "",
                                "python",
                                "",
                                child,
                                not_run=(
                                    _python_is_skipped(
                                        node.decorator_list, modules, names
                                    )
                                    or _python_is_skipped(
                                        child.decorator_list, modules, names
                                    )
                                ),
                            )
                        )
    return tests


def _python_base_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _python_base_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _python_definitions(
    tree: ast.Module, file: str
) -> dict[str, list[_Definition]]:
    tests = _python_tests(tree)
    test_owned: set[int] = set()
    for test in tests:
        test_owned.update(
            id(node)
            for node in ast.walk(test.node)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
    definitions: dict[str, list[_Definition]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if id(node) in test_owned:
            continue
        positional = [*node.args.posonlyargs, *node.args.args]
        params = tuple(arg.arg for arg in positional)
        receiver = bool(params and params[0] in {"self", "cls"})
        definitions.setdefault(node.name, []).append(
            _Definition(
                node.name, params, file, node.lineno, receiver, language="python"
            )
        )
    return {
        name: sorted(values, key=lambda item: (item.file or "", item.line or 0))
        for name, values in definitions.items()
    }


def _python_call_names(tests: Iterable[_Test]) -> set[str]:
    names: set[str] = set()
    for test in tests:
        for node in _python_scope_nodes(test.node):
            if not isinstance(node, ast.Call) or _python_is_hypothesis_call(
                node.func, test
            ):
                continue
            name = _python_target_name(node.func, test.python_imports)
            if name:
                names.add(name)
            if _python_name(node.func) in {"assertRaises", "raises"} and len(
                node.args
            ) >= 2:
                callable_name = _python_target_name(
                    node.args[1], test.python_imports
                )
                if callable_name:
                    names.add(callable_name)
    return names


def _python_root_name(node: ast.expr) -> str | None:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _python_imported_call_names(
    tree: ast.Module, tests: Iterable[_Test]
) -> set[str]:
    tests = tuple(tests)
    names: set[str] = set()
    for test in tests:
        for node in _python_scope_nodes(test.node):
            if not isinstance(node, ast.Call) or _python_is_hypothesis_call(
                node.func, test
            ):
                continue
            name = _python_target_name(node.func, test.python_imports)
            if name and (
                isinstance(node.func, ast.Attribute)
                or name in test.python_imported_names
            ):
                names.add(name)
            if _python_name(node.func) in {"assertRaises", "raises"} and len(
                node.args
            ) >= 2:
                callable_name = _python_target_name(
                    node.args[1], test.python_imports
                )
                if callable_name and (
                    isinstance(node.args[1], ast.Attribute)
                    or callable_name in test.python_imported_names
                ):
                    names.add(callable_name)
    return names


def _rust_identifier(node: Any, source_bytes: bytes) -> str | None:
    if node is None:
        return None
    if node.type == "identifier":
        return source_bytes[node.start_byte : node.end_byte].decode("utf-8", "replace")
    if node.type in {"mut_pattern", "ref_pattern"} and node.named_children:
        return _rust_identifier(node.named_children[-1], source_bytes)
    return None


def _rust_params(fn_node: Any, source_bytes: bytes) -> tuple[str, ...]:
    params_node = fn_node.child_by_field_name("parameters")
    if params_node is None:
        return ()
    params: list[str] = []
    for param in params_node.named_children:
        if param.type == "self_parameter":
            params.append("self")
        elif param.type == "parameter":
            name = _rust_identifier(param.child_by_field_name("pattern"), source_bytes)
            if name is None:
                return ()
            params.append(name)
    return tuple(params)


def _rust_function_nodes(root: Any) -> Iterable[Any]:
    for node in _walk(root):
        if node.type == "function_item":
            yield node


def _rust_source_error(root: Any, source: str, file: str) -> dict[str, Any] | None:
    if not root.has_error:
        return None
    error_node = next(
        (node for node in _walk(root) if node.is_error or node.is_missing),
        root,
    )
    line = error_node.start_point.row + 1
    lines = source.splitlines()
    text = lines[line - 1].strip() if line <= len(lines) else ""
    return {
        "test": None,
        "file": file,
        "line": line,
        "reason": "parse_error",
        "text": text,
    }


def _rust_matching_delimiter(text: str, start: int) -> int | None:
    opening = text[start]
    closing = {"(": ")", "{": "}", "[": "]"}.get(opening)
    if closing is None:
        return None
    stack = [closing]
    quote: str | None = None
    escaped = False
    index = start + 1
    while index < len(text):
        char = text[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in {"'", '"'}:
            quote = char
        elif text.startswith("//", index):
            end = text.find("\n", index)
            index = len(text) if end < 0 else end
        elif text.startswith("/*", index):
            end = text.find("*/", index + 2)
            index = len(text) if end < 0 else end + 1
        elif char in "({[":
            stack.append({"(": ")", "{": "}", "[": "]"}[char])
        elif char in ")}]":
            if not stack or char != stack.pop():
                return None
            if not stack:
                return index
        index += 1
    return None


def _split_rust_top_level(text: str) -> list[str]:
    parts: list[str] = []
    start = 0
    index = 0
    while index < len(text):
        if text[index] in "({[":
            closing = _rust_matching_delimiter(text, index)
            if closing is None:
                return [text]
            index = closing
        elif text[index] == ",":
            parts.append(text[start:index].strip())
            start = index + 1
        index += 1
    if text[start:].strip():
        parts.append(text[start:].strip())
    return parts


def _rust_proptest_strategy(
    text: str, name: str
) -> tuple[dict[str, Any] | None, str | None]:
    strategy = text.strip()
    any_match = re.fullmatch(
        r"(?:[A-Za-z_]\w*::)*any\s*::\s*<\s*(i64|bool)\s*>\s*\(\s*\)",
        strategy,
    )
    if any_match:
        return {"name": name, "type": any_match.group(1)}, None
    range_match = re.fullmatch(
        r"(-?\d[\d_]*(?:i64)?)\s*(\.\.=|\.\.)\s*"
        r"(-?\d[\d_]*(?:i64)?)",
        strategy,
    )
    if not range_match:
        return None, "unsupported_strategy"
    try:
        lower = _rust_integer(range_match.group(1))
        upper = _rust_integer(range_match.group(3))
    except ValueError:
        return None, "unsupported_strategy"
    inclusive = range_match.group(2) == "..="
    if lower < _MIN_I64 or lower > _MAX_I64 or upper < _MIN_I64 or upper > _MAX_I64:
        return None, "unsupported_strategy"
    if (inclusive and lower > upper) or (not inclusive and lower >= upper):
        return None, "unsupported_strategy"
    maximum = upper if inclusive else upper - 1
    return {"name": name, "type": "i64", "min": lower, "max": maximum}, None


def _rust_proptest_tests(
    root: Any, source_bytes: bytes, file: str
) -> list[_Test]:
    tests: list[_Test] = []
    for macro in _walk(root):
        if macro.type != "macro_invocation" or _rust_macro_name(macro, source_bytes) != "proptest":
            continue
        token_tree = next(
            (child for child in macro.children if child.type == "token_tree"), None
        )
        if token_tree is None:
            continue
        raw = source_bytes[token_tree.start_byte:token_tree.end_byte].decode(
            "utf-8", "replace"
        )
        inner = raw[1:-1] if raw.startswith("{") and raw.endswith("}") else raw
        for test_attr in re.finditer(r"#\s*\[\s*test\s*\]", inner):
            function = re.search(
                r"\bfn\s+([A-Za-z_]\w*)\s*\(", inner[test_attr.end():]
            )
            if function is None:
                continue
            name = function.group(1)
            open_paren = test_attr.end() + function.end() - 1
            close_paren = _rust_matching_delimiter(inner, open_paren)
            if close_paren is None:
                continue
            body_open = inner.find("{", close_paren + 1)
            body_close = _rust_matching_delimiter(inner, body_open) if body_open >= 0 else None
            if body_close is None:
                continue
            attr_boundary = max(inner.rfind("}", 0, test_attr.start()), 0)
            test_attributes = inner[attr_boundary:body_open]
            should_panic = bool(re.search(r"#\s*\[\s*should_panic\b", test_attributes))
            not_run = bool(re.search(r"#\s*\[\s*ignore\b", test_attributes))
            parameter_text = inner[open_paren + 1:close_paren]
            variables: list[dict[str, Any]] = []
            skip_reason: str | None = None
            generated_params: list[str] = []
            for parameter in _split_rust_top_level(parameter_text):
                match = re.fullmatch(
                    r"\s*(mut\s+)?([A-Za-z_]\w*)\s+in\s+(.+?)\s*",
                    parameter,
                    re.DOTALL,
                )
                if match is None:
                    skip_reason = "unsupported_strategy"
                    continue
                mutable, variable, strategy = match.groups()
                parsed, reason = _rust_proptest_strategy(strategy, variable)
                if mutable:
                    skip_reason = "generator_variable_rebound"
                if parsed is None:
                    if skip_reason != "generator_variable_rebound":
                        skip_reason = reason
                    variables.append({"name": variable, "type": "i64"})
                elif mutable:
                    variables.append(parsed)
                else:
                    variables.append(parsed)
                generated_type = "bool" if parsed and parsed["type"] == "bool" else "i64"
                generated_params.append(f"{variable}: {generated_type}")
            if not variables:
                skip_reason = skip_reason or "unsupported_strategy"
            replacement = "(" + ", ".join(generated_params) + "\n" * parameter_text.count("\n") + ")"
            header = inner[test_attr.start():body_open + 1]
            local_open = open_paren - test_attr.start()
            local_close = close_paren - test_attr.start()
            generated = header[:local_open] + replacement + header[local_close + 1:]
            generated += inner[body_open + 1:body_close + 1]
            padding = macro.start_point.row + inner[:test_attr.start()].count("\n")
            synthetic = "\n" * padding + generated
            tree, generated_bytes = tree_sitter_extract.parse(synthetic, "rust")
            if tree is None or generated_bytes is None or tree.root_node.has_error:
                continue
            fn_node = next(
                (
                    node for node in _rust_function_nodes(tree.root_node)
                    if _rust_identifier(node.child_by_field_name("name"), generated_bytes) == name
                ),
                None,
            )
            if fn_node is None:
                continue
            tests.append(
                _Test(
                    name,
                    file,
                    "rust",
                    synthetic,
                    fn_node,
                    should_panic=should_panic,
                    not_run=not_run,
                    property_test=True,
                    property_variables=tuple(variables),
                    property_skip_reason=skip_reason,
                )
            )
    return tests


def _rust_macro_path(node: Any, source_bytes: bytes) -> str:
    if not node.named_children:
        return ""
    return source_bytes[
        node.named_children[0].start_byte : node.named_children[0].end_byte
    ].decode("utf-8", "replace")


def _rust_macro_name(node: Any, source_bytes: bytes) -> str:
    return _rust_macro_path(node, source_bytes).split("::")[-1].strip()


def _rust_standard_path(path: str) -> bool:
    return path.lstrip(":").startswith(("std::", "core::"))


def _rust_attribute_names(fn_node: Any, source_bytes: bytes) -> set[str]:
    parent = fn_node.parent
    if parent is None:
        return set()
    siblings = parent.named_children
    index = next(
        (
            index
            for index, sibling in enumerate(siblings)
            if sibling.start_byte == fn_node.start_byte
        ),
        None,
    )
    if index is None:
        return set()
    attributes: set[str] = set()
    for sibling in reversed(siblings[:index]):
        if sibling.type != "attribute_item":
            break
        text = _rust_text(sibling, source_bytes)
        attribute = text[2:-1].strip() if text.startswith("#[") else ""
        name = attribute.split("(", 1)[0].split("=", 1)[0].strip().split("::")[-1]
        if name:
            attributes.add(name)
    return attributes


def _rust_use_names(node: Any, source_bytes: bytes) -> set[str]:
    argument = node.child_by_field_name("argument")
    if argument is None:
        return set()
    names: set[str] = set()
    if argument.type == "scoped_identifier":
        path = _rust_text(argument, source_bytes)
        if not _rust_standard_path(path):
            name_node = argument.child_by_field_name("name")
            name = _rust_text(name_node, source_bytes) if name_node is not None else ""
            if name:
                names.add(name)
    elif argument.type == "use_as_clause":
        path_node = argument.child_by_field_name("path")
        alias_node = argument.child_by_field_name("alias")
        path = _rust_text(path_node, source_bytes) if path_node is not None else ""
        alias = _rust_text(alias_node, source_bytes) if alias_node is not None else ""
        if alias and not _rust_standard_path(path):
            names.add(alias)
    elif argument.type == "identifier":
        names.add(_rust_text(argument, source_bytes))
    elif argument.type == "scoped_use_list":
        prefix_node = argument.child_by_field_name("path")
        list_node = argument.child_by_field_name("list")
        prefix = _rust_text(prefix_node, source_bytes) if prefix_node is not None else ""
        if _rust_standard_path(prefix) or list_node is None:
            return names
        for item in list_node.named_children:
            if item.type == "use_wildcard":
                continue
            if item.type == "use_as_clause":
                path_node = item.child_by_field_name("path")
                alias_node = item.child_by_field_name("alias")
                path = _rust_text(path_node, source_bytes) if path_node is not None else ""
                full_path = f"{prefix}::{path}"
                alias = _rust_text(alias_node, source_bytes) if alias_node is not None else ""
                if alias and not _rust_standard_path(full_path):
                    names.add(alias)
            elif item.type == "identifier":
                names.add(_rust_text(item, source_bytes))
            elif item.type == "scoped_identifier":
                path = f"{prefix}::{_rust_text(item, source_bytes)}"
                name_node = item.child_by_field_name("name")
                name = _rust_text(name_node, source_bytes) if name_node is not None else ""
                if name and not _rust_standard_path(path):
                    names.add(name)
            elif item.type == "scoped_use_list":
                names.update(_rust_use_names_for_scoped_list(item, source_bytes))
    return names


def _rust_use_names_for_scoped_list(node: Any, source_bytes: bytes) -> set[str]:
    names: set[str] = set()
    prefix_node = node.child_by_field_name("path")
    list_node = node.child_by_field_name("list")
    prefix = _rust_text(prefix_node, source_bytes) if prefix_node is not None else ""
    if _rust_standard_path(prefix) or list_node is None:
        return names
    for item in list_node.named_children:
        if item.type == "use_wildcard":
            continue
        if item.type == "use_as_clause":
            alias_node = item.child_by_field_name("alias")
            alias = _rust_text(alias_node, source_bytes) if alias_node is not None else ""
            if alias:
                names.add(alias)
        elif item.type == "identifier":
            names.add(_rust_text(item, source_bytes))
        elif item.type == "scoped_identifier":
            name_node = item.child_by_field_name("name")
            name = _rust_text(name_node, source_bytes) if name_node is not None else ""
            if name:
                names.add(name)
    return names


def _rust_imported_names(
    root: Any, source_bytes: bytes, tests: Iterable[_Test] = ()
) -> set[str]:
    names: set[str] = set()
    import_nodes = list(_rust_scope_nodes(root))
    for test in tests:
        import_nodes.extend(_rust_scope_nodes(test.node))
    for node in import_nodes:
        if node.type == "use_declaration":
            names.update(_rust_use_names(node, source_bytes))
    return names


def _rust_source_info(
    source: str, file: str
) -> tuple[
    dict[str, list[_Definition]], list[_Test], dict[str, Any] | None, Any, bytes
]:
    tree, source_bytes = tree_sitter_extract.parse(source, "rust")
    if tree is None or source_bytes is None:
        return {}, [], {
            "test": None,
            "file": file,
            "line": 1,
            "reason": "parse_error",
            "text": "Rust parser unavailable",
        }, None, b""
    parse_error = _rust_source_error(tree.root_node, source, file)
    if parse_error is not None:
        return {}, [], parse_error, tree, source_bytes
    function_nodes = list(_rust_function_nodes(tree.root_node))
    attributes = {
        id(fn_node): _rust_attribute_names(fn_node, source_bytes)
        for fn_node in function_nodes
    }
    test_node_starts = {
        fn_node.start_byte
        for fn_node in function_nodes
        if "test" in attributes[id(fn_node)]
    }
    definitions: dict[str, list[_Definition]] = {}
    tests: list[_Test] = []
    for fn_node in function_nodes:
        fn_attributes = attributes[id(fn_node)]
        name_node = fn_node.child_by_field_name("name")
        name = _rust_identifier(name_node, source_bytes)
        if name is None:
            continue
        if "test" in fn_attributes:
            tests.append(
                _Test(
                    name,
                    file,
                    "rust",
                    source,
                    fn_node,
                    should_panic="should_panic" in fn_attributes,
                    not_run="ignore" in fn_attributes,
                )
            )
            continue
        ancestor = fn_node.parent
        nested_in_test = False
        while ancestor is not None:
            if (
                ancestor.type == "function_item"
                and ancestor.start_byte in test_node_starts
            ):
                nested_in_test = True
                break
            ancestor = ancestor.parent
        if nested_in_test:
            continue
        definitions.setdefault(name, []).append(
            _Definition(
                name,
                _rust_params(fn_node, source_bytes),
                file,
                name_node.start_point.row + 1,
                bool(_rust_params(fn_node, source_bytes)[:1] == ("self",)),
                language="rust",
            )
        )
    tests.extend(_rust_proptest_tests(tree.root_node, source_bytes, file))
    definitions = {
        name: sorted(values, key=lambda item: (item.file or "", item.line or 0))
        for name, values in definitions.items()
    }
    return definitions, tests, None, tree, source_bytes


def _rust_tokens(text: str) -> list[_Token]:
    tokens: list[_Token] = []
    index = 0
    operators = ("::", "&&", "||", "==", "!=", "<=", ">=")
    while index < len(text):
        char = text[index]
        if char.isspace():
            index += 1
            continue
        if char.isdigit():
            end = index + 1
            while end < len(text) and (
                text[end].isalnum() or text[end] == "_"
            ):
                end += 1
            tokens.append(_Token("number", text[index:end]))
            index = end
            continue
        if char.isalpha() or char == "_":
            end = index + 1
            while end < len(text) and (
                text[end].isalnum() or text[end] == "_"
            ):
                end += 1
            tokens.append(_Token("identifier", text[index:end]))
            index = end
            continue
        if char in {"'", '"'}:
            quote = char
            end = index + 1
            escaped = False
            while end < len(text):
                current = text[end]
                end += 1
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == quote:
                    break
            tokens.append(_Token("literal_other", text[index:end]))
            index = end
            continue
        operator = next(
            (candidate for candidate in operators if text.startswith(candidate, index)),
            None,
        )
        if operator is not None:
            tokens.append(_Token("operator", operator))
            index += len(operator)
            continue
        if char in "()[]{} ,+-*/% !<>".replace(" ", ""):
            kind = "punctuation" if char in "(),[]{}" else "operator"
            tokens.append(_Token(kind, char))
            index += 1
            continue
        tokens.append(_Token("unknown", char))
        index += 1
    return tokens


def _rust_integer(text: str) -> int:
    raw = text
    for suffix in (
        "i128",
        "u128",
        "usize",
        "isize",
        "i64",
        "u64",
        "i32",
        "u32",
        "i16",
        "u16",
        "i8",
        "u8",
    ):
        if raw.endswith(suffix):
            raw = raw[: -len(suffix)]
            break
    raw = raw.replace("_", "")
    if raw.lower().startswith(("0x", "0b", "0o")):
        return int(raw, 0)
    return int(raw, 10)


class _RustExpressionParser:
    def __init__(self, text: str):
        self.tokens = _rust_tokens(text)
        self.index = 0

    def _peek(self) -> str | None:
        return self.tokens[self.index].text if self.index < len(self.tokens) else None

    def _take(self) -> _Token:
        if self.index >= len(self.tokens):
            raise _ExpressionError("unexpected end of expression")
        token = self.tokens[self.index]
        self.index += 1
        return token

    def _expect(self, text: str) -> None:
        if self._take().text != text:
            raise _ExpressionError(f"expected {text}")

    def parse(self) -> _Expr:
        if not self.tokens:
            raise _ExpressionError("empty expression")
        expression = self._parse_expression(0)
        if self.index != len(self.tokens):
            raise _ExpressionError("unexpected token")
        return expression

    def parse_arguments(self) -> list[_Expr]:
        expressions: list[_Expr] = []
        if not self.tokens:
            return expressions
        while self.index < len(self.tokens):
            expressions.append(self._parse_expression(0))
            if self._peek() != ",":
                break
            self._take()
        if self.index != len(self.tokens):
            raise _ExpressionError("unexpected macro argument")
        return expressions

    def _parse_expression(self, minimum: int) -> _Expr:
        left = self._parse_prefix()
        while True:
            operator = self._peek()
            precedence = _BINARY_OPERATORS.get(
                operator or "", _UNSUPPORTED_BINARY_OPERATORS.get(operator or "")
            )
            if precedence is None or precedence < minimum:
                break
            self._take()
            right = self._parse_expression(precedence + 1)
            if operator in {"==", "!=", "<", "<=", ">", ">="}:
                if left.kind == "compare":
                    left = _Expr(
                        "compare",
                        (*left.value, operator),
                        (*left.children, right),
                    )
                else:
                    left = _Expr("compare", (operator,), (left, right))
            elif operator in {"&&", "||"}:
                kind = "boolean"
                if left.kind == kind and left.value == operator:
                    left = _Expr(kind, operator, (*left.children, right))
                else:
                    left = _Expr(kind, operator, (left, right))
            elif operator in _UNSUPPORTED_BINARY_OPERATORS:
                left = _Expr("unsupported", children=(left, right))
            else:
                left = _Expr("binary", operator, (left, right))
        return left

    def _parse_prefix(self) -> _Expr:
        token = self._peek()
        if token in {"-", "+", "!"}:
            operator = self._take().text
            expression = self._parse_expression(6)
            return _Expr("unary", operator, (expression,))
        if token == "(":
            self._take()
            expression = self._parse_expression(0)
            self._expect(")")
            return self._parse_postfix(expression)
        current = self._take()
        if current.kind == "number":
            try:
                expression = _Expr("literal", _rust_integer(current.text))
            except ValueError as exc:
                raise _ExpressionError("invalid integer literal") from exc
            return self._parse_postfix(expression)
        if current.kind == "identifier":
            parts = [current.text]
            while self._peek() == "::":
                self._take()
                next_part = self._take()
                if next_part.kind != "identifier":
                    raise _ExpressionError("invalid path")
                parts.append(next_part.text)
            path = "::".join(parts)
            name = parts[-1]
            if len(parts) == 1 and name == "true":
                expression = _Expr("literal", True)
            elif len(parts) == 1 and name == "false":
                expression = _Expr("literal", False)
            else:
                expression = _Expr("name", path)
            return self._parse_postfix(expression)
        if current.kind == "literal_other":
            return _Expr("unsupported")
        raise _ExpressionError("unsupported expression")

    def _parse_postfix(self, expression: _Expr) -> _Expr:
        while self._peek() == "(":
            self._take()
            arguments: list[_Expr] = []
            if self._peek() != ")":
                while True:
                    arguments.append(self._parse_expression(0))
                    if self._peek() != ",":
                        break
                    self._take()
                    if self._peek() == ")":
                        break
            self._expect(")")
            path = expression.value if expression.kind == "name" else None
            name = (
                path.split("::")[-1]
                if path is not None and not _rust_standard_path(path)
                else None
            )
            expression = _Expr(
                "call",
                (name, False, bool(path and "::" in path)),
                tuple(arguments),
            )
        return expression


def _parse_rust_expression(text: str) -> _Expr:
    return _RustExpressionParser(text).parse()


def _split_rust_macro_arguments(text: str) -> list[str]:
    tokens = _rust_tokens(text)
    if len(tokens) < 2 or tokens[0].text not in {"(", "{", "["}:
        raise _ExpressionError("macro arguments need a delimiter")
    closing = {"(": ")", "{": "}", "[": "]"}[tokens[0].text]
    if tokens[-1].text != closing:
        raise _ExpressionError("unclosed macro arguments")
    inner = tokens[1:-1]
    parts: list[list[_Token]] = []
    current: list[_Token] = []
    depth = 0
    for token in inner:
        if token.text in {"(", "{", "["}:
            depth += 1
        elif token.text in {")", "}", "]"}:
            depth -= 1
        if token.text == "," and depth == 0:
            parts.append(current)
            current = []
        else:
            current.append(token)
    if current or parts:
        parts.append(current)
    return [
        " ".join(token.text for token in part)
        for part in parts
        if part
    ]


def _rust_macro_arguments(
    node: Any, source_bytes: bytes, limit: int | None = None
) -> list[_Expr]:
    token_tree = next(
        (child for child in node.children if child.type == "token_tree"), None
    )
    if token_tree is None:
        raise _ExpressionError("macro has no token tree")
    text = source_bytes[token_tree.start_byte : token_tree.end_byte].decode(
        "utf-8", "replace"
    )
    parts = _split_rust_macro_arguments(text)
    if limit is not None:
        parts = parts[:limit]
    return [_parse_rust_expression(part) for part in parts]


def _rust_scope_nodes(node: Any) -> Iterable[Any]:
    yield node
    for child in node.children:
        if child.type in {"function_item", "closure_expression"}:
            continue
        yield from _rust_scope_nodes(child)


def _rust_sync_scope_nodes(node: Any) -> Iterable[Any]:
    yield node
    for child in node.children:
        if child.type in {"function_item", "closure_expression", "async_block"}:
            continue
        yield from _rust_sync_scope_nodes(child)


def _rust_call_names(
    tests: Iterable[_Test], source_bytes_by_file: dict[str, bytes]
) -> tuple[set[str], set[str]]:
    names: set[str] = set()
    qualified_names: set[str] = set()

    def record(expression: _Expr) -> None:
        for call in _walk(expression):
            if call.kind != "call" or not call.value[0]:
                continue
            names.add(call.value[0])
            if len(call.value) > 2 and call.value[2]:
                qualified_names.add(call.value[0])

    for test in tests:
        source_bytes = (
            test.source.encode("utf-8")
            if test.property_test
            else source_bytes_by_file[test.file]
        )
        for node in _rust_scope_nodes(test.node):
            if node.type == "call_expression":
                try:
                    record(_parse_rust_expression(_rust_text(node, source_bytes)))
                except _ExpressionError:
                    continue
            elif node.type == "macro_invocation":
                macro_path = _rust_macro_path(node, source_bytes)
                if _rust_standard_path(macro_path):
                    continue
                macro_name = _rust_macro_name(node, source_bytes)
                if macro_name not in {
                    "assert", "assert_eq", "assert_ne",
                    "prop_assert", "prop_assert_eq", "prop_assert_ne",
                }:
                    continue
                try:
                    limit = 1 if macro_name in {"assert", "prop_assert"} else 2
                    for expression in _rust_macro_arguments(
                        node, source_bytes, limit
                    ):
                        record(expression)
                except _ExpressionError:
                    continue
    return names, qualified_names


def _called_names(expression: _Expr) -> set[str]:
    names: set[str] = set()
    for node in _walk(expression):
        if node.kind == "call" and node.value[0]:
            names.add(node.value[0])
    return names


def _literal_value(expression: _Expr, bindings: dict[str, int | bool]) -> int | bool:
    if expression.kind == "literal":
        if isinstance(expression.value, bool):
            return expression.value
        if isinstance(expression.value, int):
            if _MIN_I64 <= expression.value <= _MAX_I64:
                return expression.value
            raise _OutOfRangeLiteralError("integer literal outside i64 range")
    if expression.kind == "name" and expression.value in bindings:
        return bindings[expression.value]
    if expression.kind == "unary" and expression.value in {"-", "+"}:
        operand = expression.children[0]
        if (
            expression.value == "-"
            and operand.kind == "literal"
            and isinstance(operand.value, int)
            and not isinstance(operand.value, bool)
            and operand.value == _MAX_I64 + 1
        ):
            return _MIN_I64
        value = _literal_value(expression.children[0], bindings)
        if isinstance(value, bool):
            raise _ExpressionError("boolean is not an integer literal")
        return -value if expression.value == "-" else value
    raise _ExpressionError("not a literal")


def _target_calls(expression: _Expr, target_names: set[str]) -> list[_Expr]:
    return [
        node
        for node in _walk(expression)
        if node.kind == "call" and node.value[0] in target_names
    ]


def _resolve_definition(
    name: str,
    file: str,
    language: str,
    definitions: dict[str, list[_Definition]],
) -> _Definition | None:
    candidates = [
        definition
        for definition in definitions.get(name, [])
        if definition.language == language
    ]
    same_file = [definition for definition in candidates if definition.file == file]
    if same_file:
        return same_file[0] if len(same_file) == 1 else None
    return candidates[0] if len(candidates) == 1 else None


def _target_metadata(
    name: str,
    language: str,
    definitions: dict[str, list[_Definition]],
) -> dict[str, Any]:
    candidates = [
        definition
        for definition in definitions.get(name, [])
        if definition.language == language
    ]
    if not candidates:
        return {"params": None, "file": None, "line": None}
    if len(candidates) == 1:
        return candidates[0].to_dict()
    return {
        "params": None,
        "ambiguous": True,
        "definitions": [
            definition.to_dict()
            for definition in sorted(
                candidates, key=lambda item: (item.file or "", item.line or 0)
            )
        ],
    }


def _render_expression(
    expression: _Expr,
    target_names: set[str],
    bindings: dict[str, int | bool],
    variable_names: set[str] | None = None,
) -> str:
    if expression.kind == "literal":
        if isinstance(expression.value, bool):
            return "true" if expression.value else "false"
        if isinstance(expression.value, int):
            if not _MIN_I64 <= expression.value <= _MAX_I64:
                raise _OutOfRangeLiteralError("integer literal outside i64 range")
            return str(expression.value)
    if expression.kind == "name":
        if expression.value in bindings:
            return _render_expression(
                _Expr("literal", bindings[expression.value]), target_names, bindings,
                variable_names,
            )
        if variable_names is not None and expression.value in variable_names:
            return expression.value
        raise _ExpressionError("unbound name")
    if expression.kind == "call":
        name, has_keywords = expression.value[:2]
        if name not in target_names or has_keywords:
            raise _ExpressionError("unsupported call")
        return "result"
    if expression.kind == "unary" and expression.value == "+":
        return _render_expression(
            expression.children[0], target_names, bindings, variable_names
        )
    if expression.kind == "unary" and expression.value in {"-", "!", "not"}:
        operand_expression = expression.children[0]
        if (
            expression.value == "-"
            and operand_expression.kind == "literal"
            and isinstance(operand_expression.value, int)
            and not isinstance(operand_expression.value, bool)
            and operand_expression.value == _MAX_I64 + 1
        ):
            return str(_MIN_I64)
        operand = _render_expression(
            expression.children[0], target_names, bindings, variable_names
        )
        operator = "!" if expression.value == "not" else expression.value
        return f"({operator}{operand})"
    if expression.kind == "binary" and expression.value in {
        "+",
        "-",
        "*",
    }:
        left = _render_expression(expression.children[0], target_names, bindings, variable_names)
        right = _render_expression(expression.children[1], target_names, bindings, variable_names)
        return f"({left} {expression.value} {right})"
    if expression.kind == "boolean" and expression.value in {"and", "or", "&&", "||"}:
        operator = {"and": "&&", "or": "||"}.get(expression.value, expression.value)
        parts = [
            _render_expression(child, target_names, bindings, variable_names)
            for child in expression.children
        ]
        return f"({f' {operator} '.join(parts)})"
    if expression.kind == "compare":
        operators = expression.value
        if len(operators) + 1 != len(expression.children):
            raise _ExpressionError("malformed comparison")
        comparisons: list[str] = []
        for index, operator in enumerate(operators):
            if operator not in {"==", "!=", "<", "<=", ">", ">="}:
                raise _ExpressionError("unsupported comparison")
            left = _render_expression(
                expression.children[index], target_names, bindings, variable_names
            )
            right = _render_expression(
                expression.children[index + 1], target_names, bindings, variable_names
            )
            comparisons.append(f"({left} {operator} {right})")
        return (
            comparisons[0]
            if len(comparisons) == 1
            else f"({' && '.join(comparisons)})"
        )
    raise _ExpressionError("unsupported expression")


def _target_argument_values(
    call: _Expr,
    definitions: dict[str, list[_Definition]],
    bindings: dict[str, int | bool],
    language: str,
    file: str,
) -> tuple[dict[str, Any] | list[Any] | None, str | None]:
    name, has_keywords = call.value[:2]
    if has_keywords:
        return None, "non_literal_argument"
    try:
        values = [_literal_value(arg, bindings) for arg in call.children]
    except _OutOfRangeLiteralError:
        return None, "unsupported_expression"
    except _ExpressionError:
        return None, "non_literal_argument"
    definition = _resolve_definition(name, file, language, definitions)
    if definition is None or definition.params is None:
        return values, None
    params = definition.params
    if definition.receiver and params[:1] in {("self",), ("cls",)}:
        params = params[1:]
    if len(values) > len(params):
        return None, "non_literal_argument"
    return dict(zip(params, values)), None


def _make_observation(
    *,
    kind: str,
    target: str,
    args: dict[str, Any] | list[Any],
    test: _Test,
    line: int,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    observation = {
        "kind": kind,
        "target": target,
        "args": args,
        "test": test.name,
        "file": test.file,
        "line": line,
    }
    if extra:
        observation.update(extra)
    return observation


def _skip(
    skipped: list[dict[str, Any]],
    *,
    test: _Test | None,
    file: str,
    line: int,
    reason: str,
    text: str,
) -> None:
    skipped.append(
        {
            "test": test.name if test is not None else None,
            "file": file,
            "line": line,
            "reason": reason,
            "text": text.strip(),
        }
    )


def _emit_assertion(
    expression: _Expr,
    *,
    test: _Test,
    line: int,
    text: str,
    bindings: dict[str, int | bool],
    target_names: set[str],
    definitions: dict[str, list[_Definition]],
    observations: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
) -> None:
    calls = _target_calls(expression, target_names)
    if not calls:
        _skip(
            skipped,
            test=test,
            file=test.file,
            line=line,
            reason="no_target_call",
            text=text,
        )
        return
    if len(calls) != 1:
        _skip(
            skipped,
            test=test,
            file=test.file,
            line=line,
            reason="multiple_target_calls",
            text=text,
        )
        return
    call = calls[0]
    args, reason = _target_argument_values(
        call, definitions, bindings, test.language, test.file
    )
    if reason is not None or args is None:
        _skip(
            skipped,
            test=test,
            file=test.file,
            line=line,
            reason=reason or "non_literal_argument",
            text=text,
        )
        return
    if (
        expression.kind == "compare"
        and expression.value == ("==",)
        and len(expression.children) == 2
    ):
        left, right = expression.children
        for candidate, expected in ((left, right), (right, left)):
            if candidate is not call:
                continue
            try:
                result = _literal_value(expected, bindings)
            except _OutOfRangeLiteralError:
                _skip(
                    skipped,
                    test=test,
                    file=test.file,
                    line=line,
                    reason="unsupported_expression",
                    text=text,
                )
                return
            except _ExpressionError:
                _skip(
                    skipped,
                    test=test,
                    file=test.file,
                    line=line,
                    reason="non_literal_argument",
                    text=text,
                )
                return
            observations.append(
                _make_observation(
                    kind="example",
                    target=call.value[0],
                    args=args,
                    test=test,
                    line=line,
                    extra={"result": result},
                )
            )
            return
    try:
        predicate = _render_expression(expression, target_names, bindings)
    except _ExpressionError:
        _skip(
            skipped,
            test=test,
            file=test.file,
            line=line,
            reason="unsupported_expression",
            text=text,
        )
        return
    observations.append(
        _make_observation(
            kind="relation",
            target=call.value[0],
            args=args,
            test=test,
            line=line,
            extra={"predicate": predicate},
        )
    )


def _python_store_counts(test_node: ast.AST) -> Counter[str]:
    store_counts: Counter[str] = Counter()
    for node in _python_scope_nodes(test_node):
        if isinstance(node, ast.Name) and isinstance(
            node.ctx, (ast.Store, ast.Del)
        ):
            store_counts[node.id] += 1
        elif isinstance(node, ast.ExceptHandler) and node.name:
            store_counts[node.name] += 1
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            store_counts[node.name] += 1
        elif isinstance(node, ast.MatchMapping) and node.rest:
            store_counts[node.rest] += 1
    scope_types = (
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.ClassDef,
        ast.Lambda,
    )

    def nested_scopes(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, scope_types):
                scope_nodes = tuple(_python_scope_write_nodes(child))
                declared_names = {
                    name
                    for scope_node in scope_nodes
                    if isinstance(scope_node, (ast.Global, ast.Nonlocal))
                    for name in scope_node.names
                }
                store_counts.update(
                    name
                    for name in _python_nested_write_names(
                        scope_nodes, declared_names
                    )
                    if name in declared_names
                )
            nested_scopes(child)

    nested_scopes(test_node)
    return store_counts


def _python_bindings(
    test_node: ast.FunctionDef | ast.AsyncFunctionDef,
    store_counts: Counter[str],
    position: tuple[int, int],
) -> dict[str, int | bool]:
    bindings: dict[str, int | bool] = {}
    for statement in test_node.body:
        statement_position = (getattr(statement, "lineno", 0), getattr(statement, "col_offset", 0))
        if statement_position >= position:
            break
        name: str | None = None
        value: ast.expr | None = None
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            if isinstance(statement.targets[0], ast.Name):
                name, value = statement.targets[0].id, statement.value
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            name, value = statement.target.id, statement.value
        if name is None or value is None or store_counts[name] != 1:
            continue
        try:
            bindings[name] = _literal_value(_python_expr(value), {})
        except _ExpressionError:
            continue
    return bindings


def _python_source_segment(source: str, node: ast.AST) -> str:
    return ast.get_source_segment(source, node) or ""


def _python_reject_block(
    with_node: ast.With | ast.AsyncWith,
    *,
    test: _Test,
    target_names: set[str],
    definitions: dict[str, list[_Definition]],
    bindings: dict[str, int | bool],
    observations: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
) -> None:
    if len(with_node.body) != 1 or not isinstance(with_node.body[0], ast.Expr):
        _skip(
            skipped,
            test=test,
            file=test.file,
            line=with_node.lineno,
            reason="ambiguous_rejects",
            text=_python_source_segment(test.source, with_node),
        )
        return
    call_node = with_node.body[0].value
    if not isinstance(call_node, ast.Call):
        _skip(
            skipped,
            test=test,
            file=test.file,
            line=with_node.lineno,
            reason="ambiguous_rejects",
            text=_python_source_segment(test.source, with_node),
        )
        return
    if _python_name(call_node.func) in {
        "assertEqual",
        "assertNotEqual",
        "assertLess",
        "assertLessEqual",
        "assertGreater",
        "assertGreaterEqual",
        "assertTrue",
        "assertFalse",
        "assertRaises",
        "raises",
    }:
        _skip(
            skipped,
            test=test,
            file=test.file,
            line=with_node.lineno,
            reason="ambiguous_rejects",
            text=_python_source_segment(test.source, with_node),
        )
        return
    expression = _python_expr(call_node, test.python_imports)
    calls = _target_calls(expression, target_names)
    if not calls:
        _skip(
            skipped,
            test=test,
            file=test.file,
            line=with_node.lineno,
            reason="no_target_call",
            text=_python_source_segment(test.source, with_node),
        )
        return
    if (
        len(calls) != 1
        or expression.kind != "call"
        or expression is not calls[0]
    ):
        _skip(
            skipped,
            test=test,
            file=test.file,
            line=with_node.lineno,
            reason="ambiguous_rejects",
            text=_python_source_segment(test.source, with_node),
        )
        return
    target_call = calls[0]
    args, reason = _target_argument_values(
        target_call, definitions, bindings, test.language, test.file
    )
    if reason is not None or args is None:
        _skip(
            skipped,
            test=test,
            file=test.file,
            line=with_node.lineno,
            reason=reason or "non_literal_argument",
            text=_python_source_segment(test.source, with_node),
        )
        return
    observations.append(
        _make_observation(
            kind="rejects",
            target=target_call.value[0],
            args=args,
            test=test,
            line=with_node.lineno,
            extra={"expected": "failure"},
        )
    )


def _python_callable_argument(node: ast.expr) -> str | None:
    if isinstance(node, (ast.Name, ast.Attribute)):
        return _python_name(node)
    return None


def _python_callable_reject(
    call_node: ast.Call,
    *,
    test: _Test,
    target_names: set[str],
    definitions: dict[str, list[_Definition]],
    bindings: dict[str, int | bool],
    observations: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
) -> None:
    text = _python_source_segment(test.source, call_node)
    line = call_node.lineno
    if len(call_node.args) < 2:
        _skip(
            skipped,
            test=test,
            file=test.file,
            line=line,
            reason="ambiguous_rejects",
            text=text,
        )
        return
    name = _python_target_name(call_node.args[1], test.python_imports)
    if name not in target_names:
        _skip(
            skipped,
            test=test,
            file=test.file,
            line=line,
            reason="no_target_call",
            text=text,
        )
        return
    expression = _Expr(
        "call",
        (name, bool(call_node.keywords)),
        tuple(_python_expr(arg, test.python_imports) for arg in call_node.args[2:]),
    )
    args, reason = _target_argument_values(
        expression, definitions, bindings, test.language, test.file
    )
    if reason is not None or args is None:
        _skip(
            skipped,
            test=test,
            file=test.file,
            line=line,
            reason=reason or "non_literal_argument",
            text=text,
        )
        return
    observations.append(
        _make_observation(
            kind="rejects",
            target=name,
            args=args,
            test=test,
            line=line,
            extra={"expected": "failure"},
        )
    )


_PYTHON_ASSERTION_CALLS = {
    "assertEqual",
    "assertNotEqual",
    "assertLess",
    "assertLessEqual",
    "assertGreater",
    "assertGreaterEqual",
    "assertTrue",
    "assertFalse",
}
_PYTHON_CONDITIONALS = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.Try,
    ast.TryStar,
    ast.Match,
)


def _python_raises_context(node: ast.With | ast.AsyncWith) -> bool:
    return any(
        isinstance(item.context_expr, ast.Call)
        and _python_name(item.context_expr.func) in {"raises", "assertRaises"}
        for item in node.items
    )


def _python_skip_nested_assertions(
    node: ast.AST,
    *,
    reason: str,
    test: _Test,
    skipped: list[dict[str, Any]],
) -> None:
    nodes = list(_python_scope_nodes(node))
    for candidate in nodes:
        if isinstance(candidate, (ast.With, ast.AsyncWith)) and _python_raises_context(candidate):
            _skip(
                skipped, test=test, file=test.file, line=candidate.lineno,
                reason="ambiguous_rejects", text=_python_source_segment(test.source, candidate),
            )
        elif isinstance(candidate, ast.Assert):
            _skip(
                skipped, test=test, file=test.file, line=candidate.lineno,
                reason=reason, text=_python_source_segment(test.source, candidate),
            )
        elif isinstance(candidate, ast.Call) and _python_name(candidate.func) in (
            _PYTHON_ASSERTION_CALLS | {"raises", "assertRaises"}
        ):
            _skip(
                skipped, test=test, file=test.file, line=candidate.lineno,
                reason=reason, text=_python_source_segment(test.source, candidate),
            )


def _python_statement_nodes(
    test: _Test, skipped: list[dict[str, Any]]
) -> list[ast.AST]:
    active: list[ast.AST] = []

    def collect(statements: list[ast.stmt], in_with: bool = False) -> str | None:
        exit_reason: str | None = None
        for statement in statements:
            if exit_reason is not None:
                _python_skip_nested_assertions(
                    statement, reason=exit_reason, test=test, skipped=skipped
                )
                continue
            if isinstance(statement, _PYTHON_CONDITIONALS):
                _python_skip_nested_assertions(
                    statement, reason="conditional_assertion", test=test, skipped=skipped
                )
                continue
            active.append(statement)
            if isinstance(statement, (ast.With, ast.AsyncWith)):
                if not _python_raises_context(statement):
                    exit_reason = collect(statement.body, in_with=True)
            elif isinstance(statement, ast.Return):
                exit_reason = "unreachable_assertion"
            elif isinstance(statement, ast.Raise):
                exit_reason = (
                    "conditional_assertion" if in_with else "unreachable_assertion"
                )
            elif isinstance(statement, ast.Expr) and isinstance(
                statement.value, ast.Call
            ):
                active.append(statement.value)
                if _python_statement_terminates(statement, test):
                    exit_reason = (
                        "conditional_assertion" if in_with else "unreachable_assertion"
                    )
        return exit_reason

    collect(test.node.body)
    return active


def _python_given_decorator(test: _Test) -> ast.Call | None:
    modules = dict(test.python_module_aliases)
    names = dict(test.python_name_aliases)
    for decorator in test.node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        name = _python_decorator_name(decorator, modules, names)
        if name in {"given", "hypothesis.given"}:
            return decorator
    return None


def _python_int_literal(node: ast.expr) -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        value = _python_int_literal(node.operand)
        return -value if value is not None else None
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.UAdd):
        return _python_int_literal(node.operand)
    return None


def _python_property_variables(
    test: _Test, given: ast.Call
) -> tuple[list[dict[str, Any]] | None, str | None]:
    params = [
        arg.arg for arg in (*test.node.args.posonlyargs, *test.node.args.args)
    ]
    if params and params[0] in {"self", "cls"}:
        params = params[1:]
    variables: list[dict[str, Any]] = []
    bound_names: set[str] = set()
    strategies = [(None, arg) for arg in given.args] + [
        (keyword.arg, keyword.value) for keyword in given.keywords
    ]
    positional_index = 0
    modules = dict(test.python_module_aliases)
    names = dict(test.python_name_aliases)
    for parameter, strategy in strategies:
        if parameter is None:
            if positional_index >= len(params):
                return None, "unsupported_strategy"
            parameter = params[positional_index]
            positional_index += 1
        if parameter is None or parameter in bound_names:
            return None, "unsupported_strategy"
        bound_names.add(parameter)
        if not isinstance(strategy, ast.Call):
            return None, "unsupported_strategy"
        strategy_name = _python_resolved_name(strategy.func, modules, names)
        if strategy_name in {"hypothesis.strategies.integers", "strategies.integers"}:
            if len(strategy.args) > 2 or any(keyword.arg not in {"min_value", "max_value"} for keyword in strategy.keywords):
                return None, "unsupported_strategy"
            if len({keyword.arg for keyword in strategy.keywords}) != len(strategy.keywords):
                return None, "unsupported_strategy"
            bound_nodes: list[ast.expr | None] = [None, None]
            for index, arg in enumerate(strategy.args):
                bound_nodes[index] = arg
            for keyword in strategy.keywords:
                index = 0 if keyword.arg == "min_value" else 1
                if bound_nodes[index] is not None:
                    return None, "unsupported_strategy"
                bound_nodes[index] = keyword.value
            lower = _python_int_literal(bound_nodes[0]) if bound_nodes[0] is not None else None
            upper = _python_int_literal(bound_nodes[1]) if bound_nodes[1] is not None else None
            if (bound_nodes[0] is not None and lower is None) or (bound_nodes[1] is not None and upper is None):
                return None, "unsupported_strategy"
            if any(
                value is not None and not _MIN_I64 <= value <= _MAX_I64
                for value in (lower, upper)
            ) or (lower is not None and upper is not None and lower > upper):
                return None, "unsupported_strategy"
            variable = {"name": parameter, "type": "i64"}
            if lower is not None:
                variable["min"] = lower
            if upper is not None:
                variable["max"] = upper
        elif strategy_name in {"hypothesis.strategies.booleans", "strategies.booleans"} and not strategy.args and not strategy.keywords:
            variable = {"name": parameter, "type": "bool"}
        else:
            return None, "unsupported_strategy"
        variables.append(variable)
    return variables, None


def _python_property_args(
    call: _Expr,
    variables: set[str],
    definitions: dict[str, list[_Definition]],
    test: _Test,
) -> tuple[dict[str, Any] | list[Any] | None, str | None]:
    name, has_keywords = call.value[:2]
    if has_keywords:
        return None, "non_literal_argument"
    values: list[Any] = []
    for argument in call.children:
        if argument.kind == "name" and argument.value in variables:
            values.append({"var": argument.value})
            continue
        try:
            values.append(_literal_value(argument, {}))
        except _OutOfRangeLiteralError:
            return None, "unsupported_expression"
        except _ExpressionError:
            return None, "non_literal_argument"
    definition = _resolve_definition(name, test.file, test.language, definitions)
    if definition is None or definition.params is None:
        return values, None
    params = definition.params
    if definition.receiver and params[:1] in {("self",), ("cls",)}:
        params = params[1:]
    if len(values) > len(params):
        return None, "non_literal_argument"
    return dict(zip(params, values)), None


def _python_property_expression(
    node: ast.expr,
    *,
    test: _Test,
    variables: set[str],
    target_names: set[str],
    definitions: dict[str, list[_Definition]],
    observations: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    variable_records: list[dict[str, Any]],
    assumptions: list[str],
) -> None:
    _python_property_expression_from_expr(
        _python_expr(node, test.python_imports),
        test=test,
        line=node.lineno,
        text=_python_source_segment(test.source, node),
        variables=variables,
        target_names=target_names,
        definitions=definitions,
        observations=observations,
        skipped=skipped,
        variable_records=variable_records,
        assumptions=assumptions,
    )


def _python_property_expression_from_expr(
    expression: _Expr,
    *,
    test: _Test,
    line: int,
    text: str,
    variables: set[str],
    target_names: set[str],
    definitions: dict[str, list[_Definition]],
    observations: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    variable_records: list[dict[str, Any]],
    assumptions: list[str],
) -> None:
    calls = _target_calls(expression, target_names)
    if not calls:
        _skip(skipped, test=test, file=test.file, line=line, reason="no_target_call", text=text)
        return
    if len(calls) != 1:
        _skip(skipped, test=test, file=test.file, line=line, reason="multiple_target_calls", text=text)
        return
    call = calls[0]
    if "result" in variables:
        _skip(skipped, test=test, file=test.file, line=line, reason="unsupported_expression", text=text)
        return
    args, reason = _python_property_args(call, variables, definitions, test)
    if reason is not None or args is None:
        _skip(skipped, test=test, file=test.file, line=line, reason=reason or "non_literal_argument", text=text)
        return
    names = {
        item.value for item in _walk(expression)
        if isinstance(item, _Expr) and item.kind == "name"
    }
    if names - variables:
        _skip(skipped, test=test, file=test.file, line=line, reason="non_literal_argument", text=text)
        return
    try:
        predicate = _render_expression(expression, target_names, {}, variables)
    except _OutOfRangeLiteralError:
        reason = "unsupported_expression"
    except _ExpressionError:
        reason = "unsupported_expression"
    else:
        observations.append(
            _make_observation(
                kind="property",
                target=call.value[0],
                args=args,
                test=test,
                line=line,
                extra={
                    "variables": [dict(variable) for variable in variable_records],
                    "assumptions": list(assumptions),
                    "predicate": predicate,
                },
            )
        )
        return
    _skip(skipped, test=test, file=test.file, line=line, reason=reason, text=text)


def _process_python_test(
    test: _Test,
    target_names: set[str],
    definitions: dict[str, list[_Definition]],
    observations: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
) -> None:
    assert isinstance(test.node, (ast.FunctionDef, ast.AsyncFunctionDef))
    if test.not_run:
        _skip(
            skipped, test=test, file=test.file, line=_python_definition_line(test.node),
            reason="test_not_run", text=_python_source_segment(test.source, test.node),
        )
        return
    given = _python_given_decorator(test)
    if given is not None:
        variables, reason = _python_property_variables(test, given)
        line = _python_definition_line(test.node)
        if variables is None:
            _skip(skipped, test=test, file=test.file, line=line, reason=reason or "unsupported_strategy", text=_python_source_segment(test.source, test.node))
            return
        variable_names = {variable["name"] for variable in variables}
        if variable_names & _python_store_counts(test.node).keys():
            _skip(
                skipped,
                test=test,
                file=test.file,
                line=line,
                reason="generator_variable_rebound",
                text=_python_source_segment(test.source, test.node),
            )
            return
        if "result" in variable_names:
            _skip(skipped, test=test, file=test.file, line=line, reason="unsupported_expression", text=_python_source_segment(test.source, test.node))
            return
        modules = dict(test.python_module_aliases)
        imported = dict(test.python_name_aliases)
        assert_nodes = [
            node for node in ast.walk(test.node)
            if isinstance(node, ast.Assert)
            or isinstance(node, ast.Call) and _python_name(node.func) in _PYTHON_ASSERTION_CALLS
        ]
        first_assert = min(
            ((node.lineno, node.col_offset) for node in assert_nodes),
            default=(10**9, 0),
        )
        assume_calls = [
            node for node in ast.walk(test.node)
            if isinstance(node, ast.Call)
            and _python_resolved_name(node.func, modules, imported).split(".")[-1] == "assume"
        ]
        valid_assumptions: list[ast.Call] = []
        top_level_assumes = {
            id(statement.value): statement.value
            for statement in test.node.body
            if isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Call)
            and _python_resolved_name(statement.value.func, modules, imported).split(".")[-1] == "assume"
        }
        for assume in assume_calls:
            if id(assume) not in top_level_assumes or (assume.lineno, assume.col_offset) >= first_assert:
                _skip(skipped, test=test, file=test.file, line=assume.lineno, reason="unsupported_assumption", text=_python_source_segment(test.source, assume))
                return
            valid_assumptions.append(assume)
        if any(
            isinstance(node, (ast.With, ast.AsyncWith)) and _python_raises_context(node)
            for node in ast.walk(test.node)
        ) or any(
            isinstance(node, ast.Call)
            and _python_name(node.func).split(".")[-1]
            in {"raises", "assertRaises"}
            for node in ast.walk(test.node)
        ):
            _skip(skipped, test=test, file=test.file, line=line, reason="unsupported_expression", text=_python_source_segment(test.source, test.node))
            return
        assumptions: list[str] = []
        for assume in sorted(valid_assumptions, key=lambda item: (item.lineno, item.col_offset)):
            if len(assume.args) != 1 or assume.keywords:
                _skip(skipped, test=test, file=test.file, line=assume.lineno, reason="unsupported_assumption", text=_python_source_segment(test.source, assume))
                return
            expression = _python_expr(assume.args[0], test.python_imports)
            if _target_calls(expression, target_names) or any(
                item.kind == "name" and item.value not in variable_names
                for item in _walk(expression)
            ):
                _skip(skipped, test=test, file=test.file, line=assume.lineno, reason="unsupported_assumption", text=_python_source_segment(test.source, assume))
                return
            try:
                assumptions.append(_render_expression(expression, set(), {}, variable_names))
            except _ExpressionError:
                _skip(skipped, test=test, file=test.file, line=assume.lineno, reason="unsupported_assumption", text=_python_source_segment(test.source, assume))
                return
        scope_nodes = _python_statement_nodes(test, skipped)
        for node in scope_nodes:
            if isinstance(node, ast.Assert):
                _python_property_expression(
                    node.test, test=test, variables=variable_names,
                    target_names=target_names, definitions=definitions,
                    observations=observations, skipped=skipped,
                    variable_records=variables, assumptions=assumptions,
                )
            elif isinstance(node, ast.Call) and _python_name(node.func) in _PYTHON_ASSERTION_CALLS:
                name = _python_name(node.func)
                if name in {"assertEqual", *tuple(_UNITTEST_ASSERTIONS)} and _python_assertion_message_allowed(node, 2):
                    op = "==" if name == "assertEqual" else _UNITTEST_ASSERTIONS[name]
                    expr = _Expr("compare", (op,), (
                        _python_expr(node.args[0], test.python_imports),
                        _python_expr(node.args[1], test.python_imports),
                    ))
                elif name in {"assertTrue", "assertFalse"} and _python_assertion_message_allowed(node, 1):
                    expr = _python_expr(node.args[0], test.python_imports)
                    if name == "assertFalse":
                        expr = _Expr("unary", "not", (expr,))
                else:
                    expr = _Expr("unsupported")
                _python_property_expression_from_expr(
                    expr, test=test, line=node.lineno,
                    text=_python_source_segment(test.source, node),
                    variables=variable_names, target_names=target_names,
                    definitions=definitions, observations=observations,
                    skipped=skipped,
                    variable_records=variables, assumptions=assumptions,
                )
        return
    store_counts = _python_store_counts(test.node)
    scope_nodes = _python_statement_nodes(test, skipped)
    context_calls: set[int] = set()
    raises_contexts: list[ast.With | ast.AsyncWith] = []
    for node in scope_nodes:
        if not isinstance(node, (ast.With, ast.AsyncWith)):
            continue
        reject_contexts: list[ast.Call] = []
        for item in node.items:
            context = item.context_expr
            if not isinstance(context, ast.Call):
                continue
            name = _python_name(context.func)
            if name not in {"raises", "assertRaises"}:
                continue
            context_calls.add(id(context))
            reject_contexts.append(context)
        if not reject_contexts:
            continue
        raises_contexts.append(node)
        if len(reject_contexts) > 1:
            _skip(
                skipped,
                test=test,
                file=test.file,
                line=node.lineno,
                reason="ambiguous_rejects",
                text=_python_source_segment(test.source, node),
            )
            continue
        bindings = _python_bindings(
            test.node, store_counts, (node.lineno, node.col_offset)
        )
        _python_reject_block(
            node,
            test=test,
            target_names=target_names,
            definitions=definitions,
            bindings=bindings,
            observations=observations,
                skipped=skipped,
            )
    raised_assertions: set[int] = set()
    assertion_methods = _PYTHON_ASSERTION_CALLS
    for with_node in raises_contexts:
        for node in _python_scope_nodes(with_node):
            if node is with_node:
                continue
            if isinstance(node, ast.Assert) or (
                isinstance(node, ast.Call)
                and _python_name(node.func) in assertion_methods
            ):
                raised_assertions.add(id(node))
    for node in scope_nodes:
        if id(node) in raised_assertions:
            continue
        if isinstance(node, ast.Assert):
            position = (node.lineno, node.col_offset)
            bindings = _python_bindings(test.node, store_counts, position)
            _emit_assertion(
                _python_expr(node.test, test.python_imports),
                test=test,
                line=node.lineno,
                text=_python_source_segment(test.source, node),
                bindings=bindings,
                target_names=target_names,
                definitions=definitions,
                observations=observations,
                skipped=skipped,
            )
        elif isinstance(node, ast.Call):
            if id(node) in context_calls:
                continue
            name = _python_name(node.func)
            if name in {"assertRaises", "raises"}:
                bindings = _python_bindings(
                    test.node, store_counts, (node.lineno, node.col_offset)
                )
                _python_callable_reject(
                    node,
                    test=test,
                    target_names=target_names,
                    definitions=definitions,
                    bindings=bindings,
                    observations=observations,
                    skipped=skipped,
                )
            elif name in assertion_methods:
                position = (node.lineno, node.col_offset)
                bindings = _python_bindings(test.node, store_counts, position)
                if name in {"assertEqual", *tuple(_UNITTEST_ASSERTIONS)}:
                    if not _python_assertion_message_allowed(node, 2):
                        expression = _Expr("unsupported")
                    else:
                        operator = "==" if name == "assertEqual" else _UNITTEST_ASSERTIONS[name]
                        expression = _Expr(
                            "compare",
                            (operator,),
                            (
                                _python_expr(node.args[0], test.python_imports),
                                _python_expr(node.args[1], test.python_imports),
                            ),
                        )
                elif name in {"assertTrue", "assertFalse"}:
                    if not _python_assertion_message_allowed(node, 1):
                        expression = _Expr("unsupported")
                    else:
                        expression = _python_expr(node.args[0], test.python_imports)
                        if name == "assertFalse":
                            expression = _Expr("unary", "not", (expression,))
                else:
                    expression = _Expr("unsupported")
                _emit_assertion(
                    expression,
                    test=test,
                    line=node.lineno,
                    text=_python_source_segment(test.source, node),
                    bindings=bindings,
                    target_names=target_names,
                    definitions=definitions,
                    observations=observations,
                    skipped=skipped,
                )


def _python_assertion_message_allowed(call: ast.Call, required_args: int) -> bool:
    if not required_args <= len(call.args) <= required_args + 1:
        return False
    if any(keyword.arg != "msg" for keyword in call.keywords):
        return False
    if len(call.keywords) > 1 or (len(call.args) > required_args and call.keywords):
        return False
    return True


def _rust_store_counts(test: _Test, source_bytes: bytes) -> Counter[str]:
    body = test.node.child_by_field_name("body")
    counts: Counter[str] = Counter()
    if body is None:
        return counts
    scope_nodes = tuple(_rust_sync_scope_nodes(body))
    outer_names = set(_rust_params(test.node, source_bytes))
    for node in scope_nodes:
        if node.type == "let_declaration":
            name = _rust_identifier(node.child_by_field_name("pattern"), source_bytes)
            if name:
                counts[name] += 1
                outer_names.add(name)
        elif node.type in {"assignment_expression", "compound_assignment_expr"}:
            left = node.child_by_field_name("left")
            name = _rust_identifier(left, source_bytes)
            if name:
                counts[name] += 1
        elif node.type in {"for_expression", "let_condition"}:
            pattern = node.child_by_field_name("pattern")
            for name in _rust_pattern_binding_names(pattern, source_bytes):
                counts[name] += 1
        elif node.type == "match_arm":
            pattern = node.child_by_field_name("pattern")
            for name in _rust_pattern_binding_names(pattern, source_bytes):
                counts[name] += 1
        elif node.type == "reference_expression" and any(
            child.type == "mutable_specifier" for child in node.children
        ):
            name = _rust_identifier(
                node.child_by_field_name("value"), source_bytes
            )
            if name:
                counts[name] += 1

    def captured_writes(node: Any) -> None:
        for child in node.children:
            if child.type == "function_item":
                continue
            if child.type in {"closure_expression", "async_block"}:
                closure_nodes = tuple(_rust_sync_scope_nodes(child))
                parameter_names: set[str] = set()
                parameters = (
                    child.child_by_field_name("parameters")
                    if child.type == "closure_expression"
                    else None
                )
                if parameters is not None:
                    for parameter in parameters.named_children:
                        pattern = parameter.child_by_field_name("pattern")
                        name = _rust_identifier(pattern, source_bytes)
                        if name:
                            parameter_names.add(name)
                for scope_node in closure_nodes:
                    if scope_node.type not in {
                        "assignment_expression",
                        "compound_assignment_expr",
                    }:
                        continue
                    name = _rust_identifier(
                        scope_node.child_by_field_name("left"), source_bytes
                    )
                    local = name in parameter_names
                    ancestor = scope_node.parent
                    while ancestor is not None and ancestor != child and not local:
                        if ancestor.type == "block":
                            local = any(
                                previous.type == "let_declaration"
                                and previous.end_byte <= scope_node.start_byte
                                and _rust_identifier(
                                    previous.child_by_field_name("pattern"),
                                    source_bytes,
                                )
                                == name
                                for previous in ancestor.named_children
                            )
                        ancestor = ancestor.parent
                    if name in outer_names and not local:
                        counts[name] += 1
                captured_writes(child)
            else:
                captured_writes(child)

    captured_writes(body)
    return counts


def _rust_pattern_binding_names(node: Any, source_bytes: bytes) -> set[str]:
    if node is None:
        return set()
    if node.type == "identifier":
        name = _rust_identifier(node, source_bytes)
        return {name} if name and name != "_" else set()
    type_node = node.child_by_field_name("type")
    names: set[str] = set()
    for child in node.named_children:
        if child == type_node:
            continue
        if node.type == "field_pattern":
            pattern = node.child_by_field_name("pattern")
            if pattern is not None:
                names.update(_rust_pattern_binding_names(pattern, source_bytes))
                continue
            field_name = node.child_by_field_name("name")
            if field_name is not None:
                names.update(
                    _rust_pattern_binding_names(field_name, source_bytes)
                )
                continue
        names.update(_rust_pattern_binding_names(child, source_bytes))
    return names


def _rust_bindings(
    test: _Test,
    source_bytes: bytes,
    store_counts: Counter[str],
    position: tuple[int, int],
) -> dict[str, int | bool]:
    body = test.node.child_by_field_name("body")
    bindings: dict[str, int | bool] = {}
    if body is None:
        return bindings
    for statement in body.named_children:
        statement_position = (statement.start_point.row, statement.start_point.column)
        if statement_position >= (position[0] - 1, position[1]):
            break
        if statement.type != "let_declaration":
            continue
        name = _rust_identifier(statement.child_by_field_name("pattern"), source_bytes)
        value_node = statement.child_by_field_name("value")
        if not name or value_node is None or store_counts[name] != 1:
            continue
        raw = source_bytes[value_node.start_byte : value_node.end_byte].decode(
            "utf-8", "replace"
        )
        try:
            bindings[name] = _literal_value(_parse_rust_expression(raw), {})
        except _ExpressionError:
            continue
    return bindings


def _rust_text(node: Any, source_bytes: bytes) -> str:
    return source_bytes[node.start_byte : node.end_byte].decode("utf-8", "replace")


def _rust_terminating_call(node: Any, source_bytes: bytes) -> bool:
    if node.type != "call_expression":
        return False
    function = node.child_by_field_name("function")
    if function is None:
        return False
    path = _rust_text(function, source_bytes).replace(" ", "")
    return path in {"std::process::exit", "process::exit"}


def _process_rust_rejects(
    test: _Test,
    source_bytes: bytes,
    target_names: set[str],
    definitions: dict[str, list[_Definition]],
    observations: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
) -> None:
    body = test.node.child_by_field_name("body")
    line = body.start_point.row + 1 if body is not None else test.node.start_point.row + 1
    text = _rust_text(body, source_bytes) if body is not None else _rust_text(test.node, source_bytes)
    if body is None:
        _skip(
            skipped,
            test=test,
            file=test.file,
            line=line,
            reason="ambiguous_rejects",
            text=text,
        )
        return
    store_counts = _rust_store_counts(test, source_bytes)
    bindings: dict[str, int | bool] = {}
    target_call: _Expr | None = None
    call_position: tuple[int, int] | None = None
    invalid_shape = False
    for statement in body.named_children:
        if statement.type == "let_declaration":
            pattern = statement.child_by_field_name("pattern")
            value_node = statement.child_by_field_name("value")
            pattern_text = _rust_text(pattern, source_bytes).strip() if pattern else ""
            if pattern_text == "_" and value_node is not None:
                if target_call is not None:
                    invalid_shape = True
                    break
                try:
                    target_call = _parse_rust_expression(
                        _rust_text(value_node, source_bytes)
                    )
                except _ExpressionError:
                    invalid_shape = True
                    break
                call_position = (
                    value_node.start_point.row + 1,
                    value_node.start_point.column,
                )
                continue
            name = _rust_identifier(pattern, source_bytes)
            if (
                target_call is not None
                or name is None
                or value_node is None
                or store_counts[name] != 1
            ):
                invalid_shape = True
                break
            try:
                bindings[name] = _literal_value(
                    _parse_rust_expression(_rust_text(value_node, source_bytes)),
                    bindings,
                )
            except _ExpressionError:
                invalid_shape = True
                break
            continue
        if statement.type in {"call_expression", "expression_statement"}:
            expressions = (
                [statement]
                if statement.type == "call_expression"
                else statement.named_children
            )
            if (
                target_call is not None
                or len(expressions) != 1
                or expressions[0].type != "call_expression"
            ):
                invalid_shape = True
                break
            try:
                target_call = _parse_rust_expression(
                    _rust_text(expressions[0], source_bytes)
                )
            except _ExpressionError:
                invalid_shape = True
                break
            call_position = (
                expressions[0].start_point.row + 1,
                expressions[0].start_point.column,
            )
            continue
        invalid_shape = True
        break
    if (
        invalid_shape
        or target_call is None
        or target_call.kind != "call"
        or target_call.value[0] not in target_names
        or any(
            call is not target_call
            for call in _target_calls(target_call, target_names)
        )
    ):
        _skip(
            skipped,
            test=test,
            file=test.file,
            line=line,
            reason="ambiguous_rejects",
            text=text,
        )
        return
    args, reason = _target_argument_values(
        target_call, definitions, bindings, test.language, test.file
    )
    if reason is not None or args is None:
        _skip(
            skipped,
            test=test,
            file=test.file,
            line=call_position[0] if call_position else line,
            reason=reason or "non_literal_argument",
            text=text,
        )
        return
    observations.append(
        _make_observation(
            kind="rejects",
            target=target_call.value[0],
            args=args,
            test=test,
            line=call_position[0] if call_position else line,
            extra={"expected": "failure"},
        )
    )


def _rust_property_args(
    call: _Expr,
    variables: set[str],
    definitions: dict[str, list[_Definition]],
    test: _Test,
) -> tuple[dict[str, Any] | list[Any] | None, str | None]:
    name, has_keywords = call.value[:2]
    if has_keywords:
        return None, "non_literal_argument"
    values: list[Any] = []
    for argument in call.children:
        if argument.kind == "name" and argument.value in variables:
            values.append({"var": argument.value})
            continue
        try:
            values.append(_literal_value(argument, {}))
        except _OutOfRangeLiteralError:
            return None, "unsupported_expression"
        except _ExpressionError:
            return None, "non_literal_argument"
    definition = _resolve_definition(name, test.file, test.language, definitions)
    if definition is None or definition.params is None:
        return values, None
    params = definition.params
    if definition.receiver and params[:1] in {("self",), ("cls",)}:
        params = params[1:]
    if len(values) > len(params):
        return None, "non_literal_argument"
    return dict(zip(params, values)), None


def _rust_property_observation(
    macro: Any,
    *,
    test: _Test,
    source_bytes: bytes,
    variables: set[str],
    assumptions: list[str],
    target_names: set[str],
    definitions: dict[str, list[_Definition]],
    observations: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
) -> None:
    line = macro.start_point.row + 1
    text = _rust_text(macro, source_bytes)
    name = _rust_macro_name(macro, source_bytes)
    try:
        args = _rust_macro_arguments(
            macro, source_bytes, 1 if name in {"assert", "prop_assert"} else 2
        )
        if name in {"assert", "prop_assert"}:
            expression = args[0] if args else _Expr("unsupported")
        elif len(args) >= 2:
            operator = "!=" if name in {"assert_ne", "prop_assert_ne"} else "=="
            expression = _Expr("compare", (operator,), (args[0], args[1]))
        else:
            expression = _Expr("unsupported")
    except _ExpressionError:
        expression = _Expr("unsupported")
    calls = _target_calls(expression, target_names)
    if not calls:
        _skip(skipped, test=test, file=test.file, line=line, reason="no_target_call", text=text)
        return
    if len(calls) != 1:
        _skip(skipped, test=test, file=test.file, line=line, reason="multiple_target_calls", text=text)
        return
    call = calls[0]
    args_value, reason = _rust_property_args(call, variables, definitions, test)
    if reason is not None or args_value is None:
        _skip(skipped, test=test, file=test.file, line=line, reason=reason or "non_literal_argument", text=text)
        return
    names = {
        item.value for item in _walk(expression)
        if isinstance(item, _Expr) and item.kind == "name"
    }
    if names - variables:
        _skip(skipped, test=test, file=test.file, line=line, reason="non_literal_argument", text=text)
        return
    try:
        predicate = _render_expression(expression, target_names, {}, variables)
    except _ExpressionError:
        _skip(skipped, test=test, file=test.file, line=line, reason="unsupported_expression", text=text)
        return
    observations.append(
        _make_observation(
            kind="property",
            target=call.value[0],
            args=args_value,
            test=test,
            line=line,
            extra={
                "variables": [dict(variable) for variable in test.property_variables],
                "assumptions": list(assumptions),
                "predicate": predicate,
            },
        )
    )


def _process_rust_property_test(
    test: _Test,
    source_bytes: bytes,
    target_names: set[str],
    definitions: dict[str, list[_Definition]],
    observations: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
) -> None:
    line = test.node.start_point.row + 1
    text = _rust_text(test.node, source_bytes)
    if test.property_skip_reason:
        _skip(skipped, test=test, file=test.file, line=line, reason=test.property_skip_reason, text=text)
        return
    if test.should_panic:
        _skip(skipped, test=test, file=test.file, line=line, reason="unsupported_expression", text=text)
        return
    variables = {item["name"] for item in test.property_variables}
    if variables & _rust_store_counts(test, source_bytes).keys():
        _skip(
            skipped,
            test=test,
            file=test.file,
            line=line,
            reason="generator_variable_rebound",
            text=text,
        )
        return
    if "result" in variables:
        _skip(skipped, test=test, file=test.file, line=line, reason="unsupported_expression", text=text)
        return
    body = test.node.child_by_field_name("body")
    if body is None:
        return
    assertion_names = {
        "assert", "assert_eq", "assert_ne",
        "prop_assert", "prop_assert_eq", "prop_assert_ne",
    }

    def is_macro(node: Any, names: set[str]) -> bool:
        return (
            node.type == "macro_invocation"
            and _rust_macro_name(node, source_bytes) in names
        )

    top_level = [
        statement.named_children[0]
        if statement.type == "expression_statement" and len(statement.named_children) == 1
        else statement
        for statement in body.named_children
    ]
    all_assumes = [
        node for node in _rust_sync_scope_nodes(body)
        if is_macro(node, {"prop_assume"})
    ]
    direct_assumes = [node for node in top_level if is_macro(node, {"prop_assume"})]
    assertions = [
        node for node in _rust_sync_scope_nodes(body)
        if is_macro(node, assertion_names)
    ]
    first_assert = min((node.start_byte for node in assertions), default=10**30)
    assumptions: list[str] = []
    for assume in all_assumes:
        if assume not in direct_assumes or assume.start_byte >= first_assert:
            _skip(skipped, test=test, file=test.file, line=assume.start_point.row + 1, reason="unsupported_assumption", text=_rust_text(assume, source_bytes))
            return
        try:
            args = _rust_macro_arguments(assume, source_bytes)
            expression = args[0] if len(args) == 1 else _Expr("unsupported")
            names = {
                item.value for item in _walk(expression)
                if isinstance(item, _Expr) and item.kind == "name"
            }
            if names - variables or _target_calls(expression, target_names):
                raise _ExpressionError("unsupported assumption")
            assumptions.append(_render_expression(expression, set(), {}, variables))
        except _ExpressionError:
            _skip(skipped, test=test, file=test.file, line=assume.start_point.row + 1, reason="unsupported_assumption", text=_rust_text(assume, source_bytes))
            return

    unreachable = False
    conditional = False
    conditional_types = {
        "if_expression", "match_expression", "loop_expression",
        "while_expression", "for_expression", "block", "closure_expression",
    }
    for statement, inner in zip(body.named_children, top_level):
        macros = [
            node for node in _rust_sync_scope_nodes(statement)
            if is_macro(node, assertion_names)
        ]
        if unreachable or conditional or inner.type in conditional_types:
            reason = "unreachable_assertion" if unreachable else "conditional_assertion"
            for macro in macros:
                _skip(skipped, test=test, file=test.file, line=macro.start_point.row + 1, reason=reason, text=_rust_text(macro, source_bytes))
            if inner.type in conditional_types and any(node.type == "try_expression" for node in _rust_sync_scope_nodes(statement)):
                conditional = True
            continue
        if is_macro(inner, {"prop_assume"}):
            continue
        if inner.type == "macro_invocation":
            for macro in macros:
                _rust_property_observation(
                    macro, test=test, source_bytes=source_bytes,
                    variables=variables, assumptions=assumptions,
                    target_names=target_names, definitions=definitions,
                    observations=observations, skipped=skipped,
                )
        else:
            for macro in macros:
                _skip(skipped, test=test, file=test.file, line=macro.start_point.row + 1, reason="conditional_assertion", text=_rust_text(macro, source_bytes))
        if inner.type == "return_expression":
            unreachable = True
        elif is_macro(inner, {"panic", "unreachable", "todo", "unimplemented"}):
            unreachable = True
        elif _rust_terminating_call(inner, source_bytes):
            unreachable = True
        elif any(node.type == "try_expression" for node in _rust_sync_scope_nodes(statement)):
            conditional = True


def _process_rust_test(
    test: _Test,
    source_bytes: bytes,
    target_names: set[str],
    definitions: dict[str, list[_Definition]],
    observations: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
) -> None:
    if test.not_run:
        line = test.node.start_point.row + 1
        _skip(
            skipped,
            test=test,
            file=test.file,
            line=line,
            reason="test_not_run",
            text=_rust_text(test.node, source_bytes),
        )
        return
    if test.property_test:
        _process_rust_property_test(
            test, source_bytes, target_names, definitions, observations, skipped
        )
        return
    if test.should_panic:
        _process_rust_rejects(
            test,
            source_bytes,
            target_names,
            definitions,
            observations,
            skipped,
        )
        return
    body = test.node.child_by_field_name("body")
    if body is None:
        return
    store_counts = _rust_store_counts(test, source_bytes)
    unreachable = False
    conditional = False
    conditional_types = {
        "if_expression", "match_expression", "loop_expression",
        "while_expression", "for_expression", "block", "closure_expression",
    }

    def assertion_macros(node: Any) -> list[Any]:
        if node.type in {"function_item", "closure_expression", "async_block"}:
            return []
        return [
            candidate for candidate in _rust_sync_scope_nodes(node)
            if candidate.type == "macro_invocation"
            and not _rust_standard_path(_rust_macro_path(candidate, source_bytes))
            and _rust_macro_name(candidate, source_bytes)
            in {"assert", "assert_eq", "assert_ne"}
        ]

    for statement in body.named_children:
        inner_statement = (
            statement.named_children[0]
            if statement.type == "expression_statement"
            and len(statement.named_children) == 1
            else statement
        )
        if unreachable:
            for macro in assertion_macros(statement):
                _skip(
                    skipped, test=test, file=test.file,
                    line=macro.start_point.row + 1,
                    reason="unreachable_assertion", text=_rust_text(macro, source_bytes),
                )
            continue
        if conditional:
            for macro in assertion_macros(statement):
                _skip(
                    skipped, test=test, file=test.file,
                    line=macro.start_point.row + 1,
                    reason="conditional_assertion", text=_rust_text(macro, source_bytes),
                )
            continue
        if inner_statement.type in conditional_types:
            for macro in assertion_macros(statement):
                _skip(
                    skipped, test=test, file=test.file,
                    line=macro.start_point.row + 1,
                    reason="conditional_assertion", text=_rust_text(macro, source_bytes),
                )
            if any(
                node.type == "try_expression"
                for node in _rust_sync_scope_nodes(statement)
            ):
                conditional = True
            continue
        macros = assertion_macros(inner_statement)
        if inner_statement.type not in {"macro_invocation"}:
            for macro in macros:
                _skip(
                    skipped, test=test, file=test.file,
                    line=macro.start_point.row + 1,
                    reason="conditional_assertion", text=_rust_text(macro, source_bytes),
                )
        else:
            for node in macros:
                line = node.start_point.row + 1
                text = _rust_text(node, source_bytes)
                try:
                    args = _rust_macro_arguments(
                        node, source_bytes, 1 if _rust_macro_name(node, source_bytes) == "assert" else 2
                    )
                    name = _rust_macro_name(node, source_bytes)
                    if name == "assert":
                        expression = args[0] if args else _Expr("unsupported")
                    elif len(args) >= 2:
                        operator = "==" if name == "assert_eq" else "!="
                        expression = _Expr("compare", (operator,), (args[0], args[1]))
                    else:
                        expression = _Expr("unsupported")
                except _ExpressionError:
                    expression = _Expr("unsupported")
                bindings = _rust_bindings(
                    test, source_bytes, store_counts, (line, node.start_point.column)
                )
                _emit_assertion(
                    expression, test=test, line=line, text=text, bindings=bindings,
                    target_names=target_names, definitions=definitions,
                    observations=observations, skipped=skipped,
                )
        if inner_statement.type == "return_expression":
            unreachable = True
        elif (
            inner_statement.type == "macro_invocation"
            and _rust_macro_name(inner_statement, source_bytes)
            in {"panic", "unreachable", "todo", "unimplemented"}
        ):
            unreachable = True
        elif _rust_terminating_call(inner_statement, source_bytes):
            unreachable = True
        elif any(
            node.type == "try_expression"
            for node in _rust_sync_scope_nodes(statement)
        ):
            conditional = True


def _common_root(inputs: list[Path]) -> Path:
    directories = [path if path.is_dir() else path.parent for path in inputs]
    try:
        return Path(os.path.commonpath([str(path) for path in directories]))
    except ValueError as exc:
        raise HarvestInputError("input paths do not share a common root") from exc


def _collect_sources(
    paths: list[Path], language: str | None
) -> tuple[list[Path], Path]:
    if language is not None and language not in {"python", "rust"}:
        raise HarvestInputError(f"unknown language: {language}")
    if not paths:
        raise HarvestInputError("at least one input path is required")
    inputs: list[Path] = []
    for path_value in paths:
        path = Path(path_value).expanduser().resolve()
        if not path.exists():
            raise HarvestInputError(f"input path does not exist: {path_value}")
        inputs.append(path)
    source_paths: set[Path] = set()
    for path in inputs:
        candidates = path.rglob("*") if path.is_dir() else (path,)
        for candidate in candidates:
            if not candidate.is_file() or candidate.suffix.lower() not in _EXTENSIONS:
                continue
            detected = _EXTENSIONS[candidate.suffix.lower()]
            if language is None or language == detected:
                source_paths.add(candidate.resolve())
    sources = sorted(source_paths, key=lambda item: str(item))
    if not sources:
        raise HarvestInputError("no Python or Rust source files found")
    return sources, _common_root(inputs)


def harvest_tests(
    paths: list[Path],
    language: str | None,
    targets: set[str] | None,
) -> dict:
    """Extract deterministic test observations from Python and Rust sources."""
    if language is not None:
        language = language.lower()
    source_paths, root = _collect_sources(paths, language)
    sources = [
        (path, path.relative_to(root).as_posix(), _EXTENSIONS[path.suffix.lower()])
        for path in source_paths
    ]
    python_modules = {
        path.parent.name if path.name == "__init__.py" else path.stem
        for path, _relative, source_language in sources
        if source_language == "python"
    }
    definitions: dict[str, list[_Definition]] = {}
    tests: list[_Test] = []
    parse_skips: list[dict[str, Any]] = []
    rust_bytes: dict[str, bytes] = {}
    call_names: set[str] = set()
    imported_call_names: set[str] = set()
    qualified_call_names: set[str] = set()
    call_names_by_language: dict[str, set[str]] = {}
    for path, relative, source_language in sources:
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise HarvestInputError(f"cannot read source file {path}: {exc}") from exc
        if source_language == "python":
            try:
                tree = ast.parse(source, filename=str(path))
            except SyntaxError as exc:
                lines = source.splitlines()
                text = (
                    lines[exc.lineno - 1].strip()
                    if exc.lineno and exc.lineno <= len(lines)
                    else str(exc)
                )
                parse_skips.append(
                    {
                        "test": None,
                        "file": relative,
                        "line": exc.lineno or 1,
                        "reason": "parse_error",
                        "text": text,
                    }
                )
                continue
            file_tests = []
            for test in _python_tests(tree):
                module_aliases, name_aliases = _python_import_aliases(
                    tree, test.node
                )
                file_tests.append(
                    _Test(
                        test.name,
                        relative,
                        "python",
                        source,
                        test.node,
                        not_run=test.not_run,
                        python_imports=_python_import_roots(
                            tree, test.node, python_modules
                        ),
                        python_imported_names=_python_imported_names(
                            tree, test.node
                        ),
                        python_module_aliases=tuple(module_aliases.items()),
                        python_name_aliases=tuple(name_aliases.items()),
                        property_test=any(
                            isinstance(decorator, ast.Call)
                            and _python_decorator_name(
                                decorator, module_aliases, name_aliases
                            )
                            in {"given", "hypothesis.given"}
                            for decorator in test.node.decorator_list
                        ),
                    )
                )
            tests.extend(file_tests)
            for name, file_definitions in _python_definitions(tree, relative).items():
                definitions.setdefault(name, []).extend(file_definitions)
            call_names.update(_python_call_names(file_tests))
            imported_call_names.update(
                _python_imported_call_names(tree, file_tests)
            )
            call_names_by_language.setdefault("python", set()).update(
                _python_call_names(file_tests)
            )
        else:
            file_definitions, file_tests, parse_error, tree, source_bytes = (
                _rust_source_info(source, relative)
            )
            if parse_error is not None:
                parse_skips.append(parse_error)
                continue
            tests.extend(file_tests)
            rust_bytes.update({test.file: source_bytes for test in file_tests})
            for name, file_definition_list in file_definitions.items():
                definitions.setdefault(name, []).extend(file_definition_list)
            file_call_names, file_qualified_names = _rust_call_names(
                file_tests, {relative: source_bytes}
            )
            call_names.update(file_call_names)
            qualified_call_names.update(file_qualified_names)
            call_names_by_language.setdefault("rust", set()).update(
                file_call_names | file_qualified_names
            )
            imported_call_names.update(
                _rust_imported_names(tree.root_node, source_bytes, file_tests)
                & file_call_names
            )
    definitions = {
        name: sorted(values, key=lambda item: (item.file or "", item.line or 0))
        for name, values in definitions.items()
    }
    if targets is None:
        target_names = (
            (set(definitions) & call_names)
            | imported_call_names
            | qualified_call_names
        )
    else:
        target_names = set(targets)
    available_languages = {source_language for _, _, source_language in sources}
    target_languages: dict[str, set[str]] = {}
    for name in target_names:
        languages = {
            definition.language
            for definition in definitions.get(name, [])
            if definition.language is not None
        }
        languages.update(
            language
            for language, names in call_names_by_language.items()
            if name in names
        )
        target_languages[name] = languages or available_languages
    observations: list[dict[str, Any]] = []
    skipped = parse_skips
    for test in tests:
        if test.language == "python":
            _process_python_test(
                test,
                target_names,
                definitions,
                observations,
                skipped,
            )
        else:
            _process_rust_test(
                test,
                test.source.encode("utf-8") if test.property_test else rust_bytes[test.file],
                target_names,
                definitions,
                observations,
                skipped,
            )
    observations.sort(
        key=lambda item: (
            item["file"],
            item["line"],
            item["kind"],
            item["target"],
            item["test"],
        )
    )
    skipped.sort(
        key=lambda item: (
            item["file"],
            item["line"],
            item["reason"],
            item["test"] or "",
            item["text"],
        )
    )
    counts = Counter(item["kind"] for item in observations)
    return {
        "schema": "mumei.test-harvest/v1",
        "sources": [relative for _path, relative, _language in sources],
        "targets": {
            name: {
                language: _target_metadata(name, language, definitions)
                for language in sorted(target_languages[name])
            }
            for name in sorted(target_names)
        },
        "observations": observations,
        "skipped": skipped,
        "totals": {
            "tests": len(tests),
            "observations": {kind: counts[kind] for kind in _OBSERVATION_KINDS},
            "skipped": len(skipped),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m agent harvest-tests",
        description="Deterministically harvest observations from Python and Rust tests.",
    )
    parser.add_argument("paths", nargs="*", help="Source files or directories.")
    parser.add_argument("--language", help="Source language: python or rust.")
    parser.add_argument(
        "--target",
        action="append",
        default=[],
        help="Restrict harvesting to a target name; may be repeated.",
    )
    parser.add_argument("--output", help="Write JSON to this file instead of stdout.")
    return parser


def main(args: argparse.Namespace | None = None) -> int:
    if args is None:
        args = build_parser().parse_args()
    try:
        report = harvest_tests(
            [Path(path) for path in args.paths],
            args.language,
            set(args.target) if args.target else None,
        )
    except HarvestInputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 4
    parse_error_files = {
        item["file"]
        for item in report["skipped"]
        if item["reason"] == "parse_error" and item["test"] is None
    }
    if report["sources"] and len(parse_error_files) == len(report["sources"]):
        print("error: no source files could be parsed", file=sys.stderr)
        return 4
    output = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        try:
            output_path = Path(args.output).expanduser()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(output, encoding="utf-8")
        except OSError as exc:
            print(f"error: cannot write output: {exc}", file=sys.stderr)
            return 4
    else:
        print(output, end="")
    return 0
