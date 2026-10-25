from __future__ import annotations

import argparse
import ast
from collections import Counter
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
from typing import Any, Iterable

from agent import tree_sitter_extract


_EXTENSIONS = {".py": "python", ".rs": "rust"}
_OBSERVATION_KINDS = ("example", "relation", "rejects")
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


def _python_expr(node: ast.expr) -> _Expr:
    if isinstance(node, ast.Constant) and (
        isinstance(node.value, bool) or isinstance(node.value, int)
    ):
        return _Expr("literal", node.value)
    if isinstance(node, ast.Name):
        return _Expr("name", node.id)
    if isinstance(node, ast.Call):
        name = _python_name(node.func)
        return _Expr(
            "call",
            (name, bool(node.keywords)),
            tuple(_python_expr(arg) for arg in node.args),
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
            (_python_expr(node.operand),),
        )
    if isinstance(node, ast.BinOp):
        op = _PYTHON_BINARY_OPERATORS.get(type(node.op))
        return _Expr(
            "binary",
            op,
            (_python_expr(node.left), _python_expr(node.right)),
        )
    if isinstance(node, ast.BoolOp):
        op = "and" if isinstance(node.op, ast.And) else (
            "or" if isinstance(node.op, ast.Or) else None
        )
        return _Expr("boolean", op, tuple(_python_expr(value) for value in node.values))
    if isinstance(node, ast.Compare):
        operators = tuple(
            _PYTHON_COMPARISON_OPERATORS.get(type(op)) for op in node.ops
        )
        return _Expr(
            "compare",
            operators,
            (_python_expr(node.left), *(_python_expr(value) for value in node.comparators)),
        )
    return _Expr(
        "unsupported",
        children=tuple(
            _python_expr(child)
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
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                tests.append(_Test(node.name, "", "python", "", node))
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
                            _Test(child.name, "", "python", "", child)
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
            _Definition(node.name, params, file, node.lineno, receiver)
        )
    return {
        name: sorted(values, key=lambda item: (item.file or "", item.line or 0))
        for name, values in definitions.items()
    }


def _python_call_names(tests: Iterable[_Test]) -> set[str]:
    names: set[str] = set()
    for test in tests:
        for node in _python_scope_nodes(test.node):
            if isinstance(node, ast.Call):
                name = _python_name(node.func)
                if name:
                    names.add(name)
                if name in {"assertRaises", "raises"} and len(node.args) >= 2:
                    callable_name = _python_callable_argument(node.args[1])
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
    imported_names: set[str] = set()
    module_names: set[str] = set()
    import_nodes = list(_python_scope_nodes(tree))
    for test in tests:
        import_nodes.extend(_python_scope_nodes(test.node))
    for node in import_nodes:
        if isinstance(node, ast.ImportFrom):
            imported_names.update(
                alias.asname or alias.name for alias in node.names
            )
        elif isinstance(node, ast.Import):
            module_names.update(
                alias.asname or alias.name.split(".", 1)[0]
                for alias in node.names
            )
    names: set[str] = set()

    def imported_name(node: ast.expr) -> str | None:
        if isinstance(node, ast.Name) and node.id in imported_names:
            return node.id
        if (
            isinstance(node, ast.Attribute)
            and _python_root_name(node) in module_names
        ):
            return node.attr
        return None

    for test in tests:
        for node in _python_scope_nodes(test.node):
            if not isinstance(node, ast.Call):
                continue
            name = imported_name(node.func)
            if name is not None:
                names.add(name)
            if (
                _python_name(node.func) in {"assertRaises", "raises"}
                and len(node.args) >= 2
            ):
                callable_name = imported_name(node.args[1])
                if callable_name is not None:
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
                    "should_panic" in fn_attributes,
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
            )
        )
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
        source_bytes = source_bytes_by_file[test.file]
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
                if macro_name not in {"assert", "assert_eq", "assert_ne"}:
                    continue
                try:
                    limit = 1 if macro_name == "assert" else 2
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
    if expression.kind == "literal" and (
        isinstance(expression.value, bool) or isinstance(expression.value, int)
    ):
        return expression.value
    if expression.kind == "name" and expression.value in bindings:
        return bindings[expression.value]
    if expression.kind == "unary" and expression.value in {"-", "+"}:
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
    definitions: dict[str, list[_Definition]],
) -> _Definition | None:
    candidates = definitions.get(name, [])
    same_file = [definition for definition in candidates if definition.file == file]
    if same_file:
        return same_file[0] if len(same_file) == 1 else None
    return candidates[0] if len(candidates) == 1 else None


def _target_metadata(
    name: str, definitions: dict[str, list[_Definition]]
) -> dict[str, Any]:
    candidates = definitions.get(name, [])
    if not candidates:
        return _Definition(name, None, None, None).to_dict()
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
) -> str:
    if expression.kind == "literal":
        if isinstance(expression.value, bool):
            return "true" if expression.value else "false"
        if isinstance(expression.value, int):
            return str(expression.value)
    if expression.kind == "name":
        if expression.value in bindings:
            return _render_expression(
                _Expr("literal", bindings[expression.value]), target_names, bindings
            )
        raise _ExpressionError("unbound name")
    if expression.kind == "call":
        name, has_keywords = expression.value[:2]
        if name not in target_names or has_keywords:
            raise _ExpressionError("unsupported call")
        return "result"
    if expression.kind == "unary" and expression.value == "+":
        return _render_expression(expression.children[0], target_names, bindings)
    if expression.kind == "unary" and expression.value in {"-", "!", "not"}:
        operand = _render_expression(expression.children[0], target_names, bindings)
        operator = "!" if expression.value == "not" else expression.value
        return f"({operator}{operand})"
    if expression.kind == "binary" and expression.value in {
        "+",
        "-",
        "*",
    }:
        left = _render_expression(expression.children[0], target_names, bindings)
        right = _render_expression(expression.children[1], target_names, bindings)
        return f"({left} {expression.value} {right})"
    if expression.kind == "boolean" and expression.value in {"and", "or", "&&", "||"}:
        operator = {"and": "&&", "or": "||"}.get(expression.value, expression.value)
        parts = [
            _render_expression(child, target_names, bindings)
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
                expression.children[index], target_names, bindings
            )
            right = _render_expression(
                expression.children[index + 1], target_names, bindings
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
    file: str,
) -> tuple[dict[str, Any] | list[Any] | None, str | None]:
    name, has_keywords = call.value[:2]
    if has_keywords:
        return None, "non_literal_argument"
    try:
        values = [_literal_value(arg, bindings) for arg in call.children]
    except _ExpressionError:
        return None, "non_literal_argument"
    definition = _resolve_definition(name, file, definitions)
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
        call, definitions, bindings, test.file
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
    store_counts = Counter(
        node.id
        for node in _python_scope_nodes(test_node)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    )
    scope_types = (
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.ClassDef,
        ast.Lambda,
    )

    def nested_scopes(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, scope_types):
                scope_nodes = tuple(_python_scope_nodes(child))
                nonlocal_names = {
                    name
                    for scope_node in scope_nodes
                    if isinstance(scope_node, ast.Nonlocal)
                    for name in scope_node.names
                }
                store_counts.update(
                    name_node.id
                    for name_node in scope_nodes
                    if isinstance(name_node, ast.Name)
                    and isinstance(name_node.ctx, ast.Store)
                    and name_node.id in nonlocal_names
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
    expression = _python_expr(call_node)
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
        target_call, definitions, bindings, test.file
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
    name = _python_callable_argument(call_node.args[1])
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
        tuple(_python_expr(arg) for arg in call_node.args[2:]),
    )
    args, reason = _target_argument_values(
        expression, definitions, bindings, test.file
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


def _process_python_test(
    test: _Test,
    target_names: set[str],
    definitions: dict[str, list[_Definition]],
    observations: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
) -> None:
    assert isinstance(test.node, (ast.FunctionDef, ast.AsyncFunctionDef))
    store_counts = _python_store_counts(test.node)
    scope_nodes = list(_python_scope_nodes(test.node))
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
    assertion_methods = {
        "assertEqual",
        "assertNotEqual",
        "assertLess",
        "assertLessEqual",
        "assertGreater",
        "assertGreaterEqual",
        "assertTrue",
        "assertFalse",
    }
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
                _python_expr(node.test),
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
            elif name in {
                "assertEqual",
                "assertNotEqual",
                "assertLess",
                "assertLessEqual",
                "assertGreater",
                "assertGreaterEqual",
                "assertTrue",
                "assertFalse",
            }:
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
                            (_python_expr(node.args[0]), _python_expr(node.args[1])),
                        )
                elif name in {"assertTrue", "assertFalse"}:
                    if not _python_assertion_message_allowed(node, 1):
                        expression = _Expr("unsupported")
                    else:
                        expression = _python_expr(node.args[0])
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
    for node in _walk(body):
        if node.type == "let_declaration":
            name = _rust_identifier(node.child_by_field_name("pattern"), source_bytes)
            if name:
                counts[name] += 1
        elif node.type in {"assignment_expression", "compound_assignment_expr"}:
            left = node.child_by_field_name("left")
            name = _rust_identifier(left, source_bytes)
            if name:
                counts[name] += 1
    return counts


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
        target_call, definitions, bindings, test.file
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


def _process_rust_test(
    test: _Test,
    source_bytes: bytes,
    target_names: set[str],
    definitions: dict[str, list[_Definition]],
    observations: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
) -> None:
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
    for node in _rust_scope_nodes(body):
        if node.type != "macro_invocation":
            continue
        if _rust_standard_path(_rust_macro_path(node, source_bytes)):
            continue
        name = _rust_macro_name(node, source_bytes)
        if name not in {"assert", "assert_eq", "assert_ne"}:
            continue
        line = node.start_point.row + 1
        text = _rust_text(node, source_bytes)
        try:
            args = _rust_macro_arguments(
                node, source_bytes, 1 if name == "assert" else 2
            )
            if name == "assert":
                expression = args[0] if args else _Expr("unsupported")
            elif len(args) >= 2:
                operator = "==" if name == "assert_eq" else "!="
                expression = _Expr(
                    "compare",
                    (operator,),
                    (args[0], args[1]),
                )
            else:
                expression = _Expr("unsupported")
        except _ExpressionError:
            expression = _Expr("unsupported")
        bindings = _rust_bindings(
            test, source_bytes, store_counts, (line, node.start_point.column)
        )
        _emit_assertion(
            expression,
            test=test,
            line=line,
            text=text,
            bindings=bindings,
            target_names=target_names,
            definitions=definitions,
            observations=observations,
            skipped=skipped,
        )


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
    definitions: dict[str, list[_Definition]] = {}
    tests: list[_Test] = []
    parse_skips: list[dict[str, Any]] = []
    rust_bytes: dict[str, bytes] = {}
    call_names: set[str] = set()
    imported_call_names: set[str] = set()
    qualified_call_names: set[str] = set()
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
            file_tests = _python_tests(tree)
            file_tests = [
                _Test(test.name, relative, "python", source, test.node)
                for test in file_tests
            ]
            tests.extend(file_tests)
            for name, file_definitions in _python_definitions(tree, relative).items():
                definitions.setdefault(name, []).extend(file_definitions)
            call_names.update(_python_call_names(file_tests))
            imported_call_names.update(
                _python_imported_call_names(tree, file_tests)
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
                rust_bytes[test.file],
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
            name: _target_metadata(name, definitions)
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
