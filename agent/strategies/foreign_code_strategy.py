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

import z3

from agent.cross_validation import (
    _dedupe_strings,
    _infer_foreign_source_line_map,
    _infer_go_contracts,
)
from agent.mumei_client import create_mumei_client


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


class ForeignCodeExtractor:
    """Extract function signatures and comment contracts from foreign code."""

    SUPPORTED_LANGUAGES = {"python", "typescript", "rust", "go"}

    def extract(self, source: str, language: str) -> list[ForeignCodeSpec]:
        normalized = language.strip().lower()
        if normalized == "python":
            return self.extract_python(source)
        if normalized == "typescript":
            return self.extract_typescript(source)
        if normalized == "rust":
            return self.extract_rust(source)
        if normalized == "go":
            return self.extract_go(source)
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
                    source_line=node.lineno,
                )
            )
        return specs

    def extract_go(self, source: str) -> list[ForeignCodeSpec]:
        """Extract Go ``func`` declarations, ``//`` contracts, and safe-path hints."""
        pattern = re.compile(
            r"(?P<comment>(?:\s*//[^\n]*\n)*)\s*"
            r"func\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*"
            r"\((?P<params>[^)]*)\)\s*(?P<ret>[\*\[\]A-Za-z0-9_]+)?",
            re.DOTALL,
        )
        inferred_atoms = {atom.name: atom for atom in _infer_go_contracts(source)}
        source_lines = _infer_foreign_source_line_map(source, "go")
        specs: list[ForeignCodeSpec] = []
        for match in pattern.finditer(source):
            function_name = _safe_identifier(match.group("name"))
            comment = _clean_go_doc(match.group("comment") or "")
            preconditions, postconditions = _contract_lines(comment)
            inferred = inferred_atoms.get(function_name)
            if inferred is not None:
                if inferred.ensures != "true":
                    postconditions = _dedupe_strings([*postconditions, inferred.ensures])
            specs.append(
                ForeignCodeSpec(
                    function_name=function_name,
                    params={
                        param.name: param.type
                        for param in inferred.params
                    }
                    if inferred is not None
                    else _go_params(match.group("params")),
                    return_type=(
                        inferred.return_type
                        if inferred is not None
                        else _go_type(match.group("ret") or "bool")
                    ),
                    preconditions=preconditions,
                    postconditions=postconditions,
                    source_line=source_lines.get(
                        function_name,
                        _line_for_offset(source, match.start("name")),
                    ),
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
                source_line = _line_for_offset(source, match.start("name"))
                specs.append(
                    ForeignCodeSpec(
                        function_name=_safe_identifier(match.group("name")),
                        params=_typescript_params(match.group("params")),
                        return_type=_typescript_type(match.group("ret") or "void"),
                        preconditions=preconditions,
                        postconditions=postconditions,
                        source_line=source_line,
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
            source_line = _line_for_offset(source, match.start("name"))
            specs.append(
                ForeignCodeSpec(
                    function_name=_safe_identifier(match.group("name")),
                    params=_rust_params(match.group("params")),
                    return_type=_rust_type(match.group("ret") or "()"),
                    preconditions=preconditions,
                    postconditions=postconditions,
                    source_line=source_line,
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
        normalized_language = _normalize_language(language)
        specs = self.extractor.extract(source_code, normalized_language)
        safety_issues = _filter_covered_safety_issues(
            _detect_safety_issues(source_code, normalized_language),
            specs,
        )
        atoms = [to_mumei_atom(spec) for spec in specs]
        mumei_source = "\n\n".join(atoms) + ("\n" if atoms else "")
        if not specs:
            return {
                "success": False,
                "language": normalized_language,
                "specs": [],
                "atoms": [],
                "source_line_map": {},
                "mumei_source": "",
                "verification": None,
                "errors": [
                    "No function signatures were extracted.",
                    *[issue.message for issue in safety_issues],
                ],
                "warnings": [],
                **_first_counterexample_payload(safety_issues),
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
            "success": bool(verification.get("success")) and not safety_issues,
            "language": normalized_language,
            "specs": [asdict(spec) for spec in specs],
            "atoms": atoms,
            "source_line_map": {spec.function_name: spec.source_line for spec in specs},
            "mumei_source": mumei_source,
            "verification": verification,
            "errors": [
                *[issue.message for issue in safety_issues],
                *([] if verification.get("success") else ["mumei verify failed"]),
            ],
            "warnings": [],
            **_first_counterexample_payload(safety_issues),
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
    parser.add_argument(
        "--file",
        required=True,
        help="Path to Python/TypeScript/Rust/Go source.",
    )
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
        return _detect_block_safety_issues(source, _go_function_blocks(source), "Go")
    if normalized == "python":
        return _detect_python_safety_issues(source)
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


def _issues_for_expression(
    function_name: str,
    expression: str,
    label: str,
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
        for value in _go_nil_dereference_values(expression):
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


def _go_nil_dereference_values(expression: str) -> list[str]:
    values: list[str] = []
    for match in re.finditer(r"\*\s*(?P<value>[A-Za-z_][A-Za-z0-9_]*)", expression):
        values.append(match.group("value"))
    for match in re.finditer(
        r"\b(?P<value>[A-Za-z_][A-Za-z0-9_]*)\s*\.",
        expression,
    ):
        values.append(match.group("value"))
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
