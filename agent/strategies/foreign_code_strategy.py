"""Extract foreign-language function contracts into Mumei atoms."""
from __future__ import annotations

import argparse
import ast
from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import re
import tempfile
from typing import Iterable

from agent.mumei_client import create_mumei_client


@dataclass(frozen=True)
class ForeignCodeSpec:
    """Function-level contract inferred from foreign source code."""

    function_name: str
    params: dict[str, str]
    return_type: str
    preconditions: list[str] = field(default_factory=list)
    postconditions: list[str] = field(default_factory=list)


class ForeignCodeExtractor:
    """Extract function signatures and comment contracts from foreign code."""

    SUPPORTED_LANGUAGES = {"python", "typescript", "rust"}

    def extract(self, source: str, language: str) -> list[ForeignCodeSpec]:
        normalized = language.strip().lower()
        if normalized == "python":
            return self.extract_python(source)
        if normalized == "typescript":
            return self.extract_typescript(source)
        if normalized == "rust":
            return self.extract_rust(source)
        raise ValueError(
            "language must be one of: "
            + ", ".join(sorted(self.SUPPORTED_LANGUAGES))
        )

    def extract_python(self, source: str) -> list[ForeignCodeSpec]:
        """Parse Python functions with ``ast``."""
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []

        specs: list[ForeignCodeSpec] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            params = {
                arg.arg: _python_type(arg.annotation)
                for arg in _python_args(node.args)
                if arg.arg not in {"self", "cls"}
            }
            doc = ast.get_docstring(node) or ""
            preconditions, postconditions = _contract_lines(doc)
            specs.append(
                ForeignCodeSpec(
                    function_name=_safe_identifier(node.name),
                    params=params,
                    return_type=_python_type(node.returns),
                    preconditions=preconditions,
                    postconditions=postconditions,
                )
            )
        return specs

    def extract_typescript(self, source: str) -> list[ForeignCodeSpec]:
        """Extract TypeScript function declarations and JSDoc contracts."""
        specs: list[ForeignCodeSpec] = []
        patterns = [
            re.compile(
                r"(?:export\s+)?(?:async\s+)?function\s+"
                r"(?P<name>[A-Za-z_$][\w$]*)\s*(?:<[^>]+>)?\s*"
                r"\((?P<params>[^)]*)\)\s*(?::\s*(?P<ret>[^{=\n]+))?",
                re.DOTALL,
            ),
            re.compile(
                r"(?:export\s+)?(?:const|let)\s+"
                r"(?P<name>[A-Za-z_$][\w$]*)\s*=\s*"
                r"(?:async\s*)?\((?P<params>[^)]*)\)\s*"
                r"(?::\s*(?P<ret>[^=]+?))?\s*=>",
                re.DOTALL,
            ),
        ]
        seen: set[tuple[str, int]] = set()
        for pattern in patterns:
            for match in pattern.finditer(source):
                key = (match.group("name"), match.start())
                if key in seen:
                    continue
                seen.add(key)
                comment = _clean_jsdoc(_preceding_jsdoc(source, match.start()))
                preconditions, postconditions = _contract_lines(comment)
                specs.append(
                    ForeignCodeSpec(
                        function_name=_safe_identifier(match.group("name")),
                        params=_typescript_params(match.group("params")),
                        return_type=_typescript_type(match.group("ret") or "void"),
                        preconditions=preconditions,
                        postconditions=postconditions,
                    )
                )
        return specs

    def extract_rust(self, source: str) -> list[ForeignCodeSpec]:
        """Extract Rust ``fn`` declarations and preceding ``///`` contracts."""
        pattern = re.compile(
            r"(?P<comment>(?:\s*///[^\n]*\n)*)\s*"
            r"(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+"
            r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?:<[^>]+>)?\s*"
            r"\((?P<params>[^)]*)\)\s*(?:->\s*(?P<ret>[^{;\n]+))?",
            re.DOTALL,
        )
        specs: list[ForeignCodeSpec] = []
        for match in pattern.finditer(source):
            comment = _clean_rust_doc(match.group("comment") or "")
            preconditions, postconditions = _contract_lines(comment)
            specs.append(
                ForeignCodeSpec(
                    function_name=_safe_identifier(match.group("name")),
                    params=_rust_params(match.group("params")),
                    return_type=_rust_type(match.group("ret") or "()"),
                    preconditions=preconditions,
                    postconditions=postconditions,
                )
            )
        return specs


class ForeignCodeVerifier:
    """Verify extracted foreign-code atoms with ``mumei verify --json``."""

    def __init__(
        self,
        mumei_bin: str = "mumei",
        mumei_client: object | None = None,
        extractor: ForeignCodeExtractor | None = None,
    ) -> None:
        self.mumei_bin = mumei_bin
        self.mumei_client = mumei_client or create_mumei_client(mumei_bin)
        self.extractor = extractor or ForeignCodeExtractor()

    def verify(self, source_code: str, language: str) -> dict[str, object]:
        specs = self.extractor.extract(source_code, language)
        atoms = [to_mumei_atom(spec) for spec in specs]
        mumei_source = "\n\n".join(atoms) + ("\n" if atoms else "")
        if not specs:
            return {
                "success": False,
                "language": language,
                "specs": [],
                "atoms": [],
                "mumei_source": "",
                "verification": None,
                "errors": ["No function signatures were extracted."],
                "warnings": [],
            }

        with tempfile.TemporaryDirectory(prefix="mumei-foreign-code-") as tmp:
            module_path = Path(tmp) / "foreign_code.mm"
            report_dir = Path(tmp) / "report"
            module_path.write_text(mumei_source, encoding="utf-8")
            verification = self.mumei_client.verify(
                str(module_path),
                report_dir=str(report_dir),
            )

        return {
            "success": bool(verification.get("success")),
            "language": language,
            "specs": [asdict(spec) for spec in specs],
            "atoms": atoms,
            "mumei_source": mumei_source,
            "verification": verification,
            "errors": [] if verification.get("success") else ["mumei verify failed"],
            "warnings": [],
        }


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


def build_parser(parser: argparse.ArgumentParser | None = None) -> argparse.ArgumentParser:
    parser = parser or argparse.ArgumentParser(description="Verify foreign code as Mumei atoms.")
    parser.add_argument("--file", required=True, help="Path to Python/TypeScript/Rust source.")
    parser.add_argument(
        "--language",
        required=True,
        choices=sorted(ForeignCodeExtractor.SUPPORTED_LANGUAGES),
        help="Source language.",
    )
    parser.add_argument("--mumei-bin", default="mumei", help="mumei CLI executable.")
    parser.add_argument("--output", help="Optional JSON report path.")
    return parser


def main(args: argparse.Namespace | None = None) -> dict[str, object]:
    args = args or build_parser().parse_args()
    source_path = Path(args.file).expanduser().resolve()
    source_code = source_path.read_text(encoding="utf-8")
    result = ForeignCodeVerifier(mumei_bin=args.mumei_bin).verify(
        source_code,
        args.language,
    )
    payload = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return result


def _python_args(args: ast.arguments) -> Iterable[ast.arg]:
    return [*args.posonlyargs, *args.args, *args.kwonlyargs]


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
