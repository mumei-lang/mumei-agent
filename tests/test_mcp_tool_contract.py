"""Offline AST drift gate for the agent MCP contract table."""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER = REPO_ROOT / "agent" / "mcp_server.py"
CONTRACT = REPO_ROOT / "docs" / "MCP_SERVER.md"


def _is_tool_decorator(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "mcp"
        and node.func.attr == "tool"
    )


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    positional = node.args.posonlyargs + node.args.args
    defaults = [None] * (len(positional) - len(node.args.defaults))
    defaults += list(node.args.defaults)
    parts: list[str] = []
    for arg, default in zip(positional, defaults):
        value = f"{arg.arg}: {ast.unparse(arg.annotation) if arg.annotation else 'Any'}"
        if default is not None:
            value += f" = {ast.unparse(default)}"
        parts.append(value)
    for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
        value = f"{arg.arg}: {ast.unparse(arg.annotation) if arg.annotation else 'Any'}"
        if default is not None:
            value += f" = {ast.unparse(default)}"
        parts.append(value)
    return ", ".join(parts)


def extract_tools(source: str) -> dict[str, str]:
    tree = ast.parse(source)
    tools: dict[str, str] = {}
    decorator_count = 0
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        count = sum(_is_tool_decorator(decorator) for decorator in node.decorator_list)
        if count:
            decorator_count += count
            tools[node.name] = _signature(node)
    literal_count = len(re.findall(r"@mcp\.tool\(", source))
    assert literal_count and decorator_count == literal_count, (
        "mcp.tool decorator extraction count mismatch: "
        f"literal={literal_count}, ast={decorator_count}"
    )
    return tools


def _split_row(line: str) -> list[str]:
    cells = [cell.strip() for cell in line.replace(r"\|", "§").split("|")]
    return cells[1:-1] if len(cells) >= 2 else []


def extract_documented_tools(text: str) -> dict[str, str]:
    match = re.search(
        r"Exported tools:\n\n\| Tool \| Arguments \| Documented return keys \|\n"
        r"\|\s*[-—]+\s*\|\s*[-—]+\s*\|\s*[-—]+\s*\|\n"
        r"(.*?)(?:\n\n|\Z)",
        text,
        re.DOTALL,
    )
    assert match, "Could not find agent MCP contract table"
    tools: dict[str, str] = {}
    for line in match.group(1).splitlines():
        cells = _split_row(line)
        if len(cells) != 3:
            continue
        name = cells[0].strip("`")
        if name:
            arguments = cells[1].replace("§", "|")
            if arguments.startswith("`") and arguments.endswith("`"):
                arguments = arguments[1:-1]
            tools[name] = arguments
    return tools


def test_agent_mcp_tool_contract_matches_ast() -> None:
    actual = extract_tools(SERVER.read_text(encoding="utf-8"))
    documented = extract_documented_tools(CONTRACT.read_text(encoding="utf-8"))
    expected = {name: signature.replace('"', "'") for name, signature in actual.items()}
    documented = {name: signature.replace('"', "'") for name, signature in documented.items()}
    assert set(expected) == set(documented)
    assert expected == documented
