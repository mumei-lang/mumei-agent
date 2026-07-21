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

from agent import tree_sitter_extract
from agent.cross_validation import (
    _dedupe_strings,
    _infer_foreign_source_line_map,
    _go_function_declarations,
    _infer_go_contracts,
    _is_go_test_name,
)
from agent.mumei_client import create_mumei_client

from agent.strategies.foreign_code_strategy_helpers import (
    ForeignCodeSpec,
    ForeignSafetyIssue,
    _balanced_brace_body,
    _clean_go_doc,
    _clean_jsdoc,
    _clean_rust_doc,
    _contract_lines,
    _contracts_cover_issue,
    _default_literal,
    _detect_block_safety_issues,
    _detect_go_safety_issues,
    _detect_python_safety_issues,
    _detect_safety_issues,
    _filter_covered_safety_issues,
    _is_go_compiler_test,
    _is_go_experimental,
    _first_counterexample_payload,
    _go_function_blocks,
    _go_nil_dereference_values,
    _go_params,
    _go_type,
    _issues_for_expression,
    _join_contracts,
    _last_rust_expression,
    _line_for_offset,
    _mumei_type,
    _normalize_contract_text,
    _normalize_language,
    _preceding_jsdoc,
    _python_args,
    _python_type,
    _python_type_name,
    _return_expressions,
    _rust_function_blocks,
    _rust_params,
    _rust_type,
    _safe_identifier,
    _solidity_params,
    _solidity_type,
    _split_params,
    _strip_contract_marker,
    _typescript_function_blocks,
    _typescript_params,
    _typescript_type,
    _z3_i64_overflow_counterexample,
    _z3_index_counterexample,
    to_mumei_atom,
)


# mumei verify statuses that are "not proven" yet not a code-safety failure.
_INCONCLUSIVE_VERIFY_STATUSES = frozenset({"trusted", "satisfiable_with_skips"})


def _is_inconclusive_verify(verification: dict[str, object] | None) -> bool:
    """True when a failed verify is inconclusive (trusted / skipped) rather than refuted."""
    if not isinstance(verification, dict):
        return False
    report = verification.get("report")
    report = report if isinstance(report, dict) else {}
    status = report.get("status") or ""
    failed = report.get("failed")
    counterexample = report.get("counterexample") or verification.get("counterexample")
    return status in _INCONCLUSIVE_VERIFY_STATUSES and not failed and not counterexample


def _match_function_pattern(
    patterns: list[re.Pattern[str]],
    source: str,
    fn: tree_sitter_extract.ExtractedFunction,
) -> re.Match[str] | None:
    """Return the regex match whose ``name`` group sits inside ``fn``'s span.

    ``fn.start_char`` / ``fn.end_char`` are character offsets into the ``str``
    ``source``, so they can be compared directly with ``match.start("name")``.
    """
    for pattern in patterns:
        for match in pattern.finditer(source):
            try:
                name_start = match.start("name")
            except IndexError:
                continue
            if fn.start_char <= name_start < fn.end_char:
                return match
    return None


def _preceding_doc_comment(source: str, start_char: int, language: str) -> str:
    """Return the raw ``///`` / ``//`` / ``/** ... */`` text before a declaration."""
    if language == "typescript":
        return _preceding_jsdoc(source, start_char)
    marker = "///" if language in ("rust", "solidity") else "//"
    lines: list[str] = []
    for line in reversed(source[:start_char].splitlines()):
        stripped = line.strip()
        if stripped.startswith(marker):
            lines.insert(0, stripped)
        elif not stripped:
            continue
        else:
            break
    return "\n".join(lines)


def _extract_go_caller_contracts(comment: str) -> list[str]:
    """Derive ``requires`` clauses from Go doc comments such as ``r must not be empty``."""
    contracts: list[str] = []
    for match in re.finditer(
        r"\b([A-Za-z_][A-Za-z0-9_]*)\s+must\s+not\s+be\s+(?:nil|empty)\b",
        comment,
        flags=re.IGNORECASE,
    ):
        contracts.append(f"{match.group(1)} != nil")
    return contracts


def _extract_go_with_tree_sitter(source: str) -> list[ForeignCodeSpec] | None:
    """Extract Go ``func`` declarations using tree-sitter, falling back to ``None``."""
    if _is_go_compiler_test(source):
        return []
    functions = tree_sitter_extract.extract_functions(source, "go", _safe_identifier)
    if functions is None:
        return None
    inferred_atoms = {atom.name: atom for atom in _infer_go_contracts(source)}
    pattern = re.compile(
        r"(?P<comment>(?:\s*//[^\n]*\n)*)\s*"
        r"func\s+(?:\([^)]*\)\s*)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
        r"(?:\[[^\]]*\])?\s*"
        r"\((?P<params>[^)]*)\)\s*"
        r"(?P<ret>(?:\([^)]*\)|[^{]+))?\s*\{",
        re.DOTALL,
    )
    specs: list[ForeignCodeSpec] = []
    for fn in functions:
        function_name = fn.name
        inferred = inferred_atoms.get(function_name)
        if not fn.has_body:
            # Assembly forward declarations and external signatures have no body;
            # emit a trusted atom so the file is not reported as unverifiable.
            if inferred is None:
                continue
            specs.append(
                ForeignCodeSpec(
                    function_name=function_name,
                    params={param.name: param.type for param in inferred.params},
                    return_type=inferred.return_type,
                    preconditions=[],
                    postconditions=[],
                    source_line=fn.line,
                )
            )
            continue
        match = _match_function_pattern([pattern], source, fn)
        if match is None:
            continue
        comment = _clean_go_doc(match.group("comment") or "")
        preconditions, postconditions = _contract_lines(comment)
        preconditions = _dedupe_strings([*preconditions, *_extract_go_caller_contracts(comment)])
        if inferred is not None and inferred.requires not in ("", "true"):
            # Inferred nil preconditions (e.g. ``c != nil`` from pointer-receiver
            # dereferences) reflect caller contracts and should be part of the spec
            # so safety issues are filtered and Mumei verifies under them.
            for req in inferred.requires.split("&&"):
                req = req.strip()
                if req and "!= nil" in req and req not in preconditions:
                    preconditions.append(req)
        if inferred is not None and inferred.ensures != "true":
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
                source_line=fn.line,
            )
        )
    return specs


def _extract_typescript_with_tree_sitter(source: str) -> list[ForeignCodeSpec] | None:
    """Extract TypeScript functions using tree-sitter, falling back to ``None``."""
    functions = tree_sitter_extract.extract_functions(
        source, "typescript", _safe_identifier
    )
    if functions is None:
        return None
    specs: list[ForeignCodeSpec] = []
    for fn in functions:
        if not fn.has_body:
            continue
        comment = _clean_jsdoc(_preceding_doc_comment(source, fn.start_char, "typescript"))
        preconditions, postconditions = _contract_lines(comment)
        specs.append(
            ForeignCodeSpec(
                function_name=fn.name,
                params=_typescript_params(fn.params_text),
                return_type=_typescript_type(
                    (fn.return_type or "").strip() or "void"
                ),
                preconditions=preconditions,
                postconditions=postconditions,
                source_line=fn.line,
            )
        )
    return specs


def _extract_rust_with_tree_sitter(source: str) -> list[ForeignCodeSpec] | None:
    """Extract Rust ``fn`` declarations using tree-sitter, falling back to ``None``."""
    functions = tree_sitter_extract.extract_functions(source, "rust", _safe_identifier)
    if functions is None:
        return None
    specs: list[ForeignCodeSpec] = []
    for fn in functions:
        if not fn.has_body:
            continue
        comment = _clean_rust_doc(_preceding_doc_comment(source, fn.start_char, "rust"))
        preconditions, postconditions = _contract_lines(comment)
        specs.append(
            ForeignCodeSpec(
                function_name=fn.name,
                params=_rust_params(fn.params_text),
                return_type=_rust_type((fn.return_type or "").strip() or "()"),
                preconditions=preconditions,
                postconditions=postconditions,
                source_line=fn.line,
            )
        )
    return specs


def _extract_solidity_with_tree_sitter(source: str) -> list[ForeignCodeSpec] | None:
    """Extract Solidity ``function`` declarations using tree-sitter, falling back to ``None``."""
    functions = tree_sitter_extract.extract_functions(
        source, "solidity", _safe_identifier
    )
    if functions is None:
        return None
    specs: list[ForeignCodeSpec] = []
    for fn in functions:
        if not fn.has_body:
            # Interface declarations and function stubs have no implementation;
            # emit them as trusted specs so the file is not marked unverifiable.
            specs.append(
                ForeignCodeSpec(
                    function_name=fn.name,
                    params=_solidity_params(fn.params_text),
                    return_type=_solidity_type(fn.return_type or "void"),
                    preconditions=[],
                    postconditions=[],
                    source_line=fn.line,
                )
            )
            continue
        comment = _clean_rust_doc(
            _preceding_doc_comment(source, fn.start_char, "solidity")
        )
        preconditions, postconditions = _contract_lines(comment)
        specs.append(
            ForeignCodeSpec(
                function_name=fn.name,
                params=_solidity_params(fn.params_text),
                return_type=_solidity_type(fn.return_type or "void"),
                preconditions=preconditions,
                postconditions=postconditions,
                source_line=fn.line,
            )
        )
    return specs


class ForeignCodeExtractor:
    """Extract function signatures and comment contracts from foreign code."""

    SUPPORTED_LANGUAGES = {"python", "typescript", "rust", "go", "solidity"}

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
        if normalized == "solidity":
            return self.extract_solidity(source)
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
        if _is_go_experimental(source):
            return []
        specs = _extract_go_with_tree_sitter(source)
        if specs is not None:
            return specs
        return self._extract_go_regex(source)

    def _extract_go_regex(self, source: str) -> list[ForeignCodeSpec]:
        """Regex fallback for Go ``func`` extraction."""
        if _is_go_compiler_test(source):
            return []
        pattern = re.compile(
            r"(?P<comment>(?:\s*//[^\n]*\n)*)\s*"
            r"func\s+(?:\([^)]*\)\s*)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
            r"(?:\[[^\]]*\])?\s*"
            r"\((?P<params>[^)]*)\)\s*"
            r"(?P<ret>(?:\([^)]*\)|[^{]+))?\s*\{",
            re.DOTALL,
        )
        inferred_atoms = {atom.name: atom for atom in _infer_go_contracts(source)}
        source_lines = _infer_foreign_source_line_map(source, "go")
        specs: list[ForeignCodeSpec] = []
        for match in pattern.finditer(source):
            function_name = _safe_identifier(match.group("name"))
            comment = _clean_go_doc(match.group("comment") or "")
            preconditions, postconditions = _contract_lines(comment)
            preconditions = _dedupe_strings([*preconditions, *_extract_go_caller_contracts(comment)])
            inferred = inferred_atoms.get(function_name)
            if inferred is not None and inferred.requires not in ("", "true"):
                for req in inferred.requires.split("&&"):
                    req = req.strip()
                    if req and "!= nil" in req and req not in preconditions:
                        preconditions.append(req)
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
        specs = _extract_typescript_with_tree_sitter(source)
        if specs is not None:
            return specs
        return self._extract_typescript_regex(source)

    def _extract_typescript_regex(self, source: str) -> list[ForeignCodeSpec]:
        """Regex fallback for TypeScript function extraction."""
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
        specs = _extract_rust_with_tree_sitter(source)
        if specs is not None:
            return specs
        return self._extract_rust_regex(source)

    def _extract_rust_regex(self, source: str) -> list[ForeignCodeSpec]:
        """Regex fallback for Rust ``fn`` extraction."""
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

    def extract_solidity(self, source: str) -> list[ForeignCodeSpec]:
        """Extract Solidity ``function`` declarations and preceding ``///`` NatSpec."""
        specs = _extract_solidity_with_tree_sitter(source)
        if specs is not None:
            return specs
        return self._extract_solidity_regex(source)

    def _extract_solidity_regex(self, source: str) -> list[ForeignCodeSpec]:
        """Regex fallback for Solidity ``function`` extraction."""
        pattern = re.compile(
            r"(?P<comment>(?:\s*///[^\n]*\n)*)\s*"
            r"function\s+(?P<name>[A-Za-z_$][\w$]*)\s*"
            r"\((?P<params>[^)]*)\)"
            r"(?P<attrs>[^{;]*?)\{",
            re.DOTALL,
        )
        specs: list[ForeignCodeSpec] = []
        for match in pattern.finditer(source):
            comment = _clean_rust_doc(match.group("comment") or "")
            preconditions, postconditions = _contract_lines(comment)
            attrs = match.group("attrs") or ""
            returns_match = re.search(r"returns\s*\((?P<ret>[^)]*)\)", attrs)
            return_type = (
                _solidity_type(returns_match.group("ret"))
                if returns_match
                else "void"
            )
            source_line = _line_for_offset(source, match.start("name"))
            specs.append(
                ForeignCodeSpec(
                    function_name=_safe_identifier(match.group("name")),
                    params=_solidity_params(match.group("params")),
                    return_type=return_type,
                    preconditions=preconditions,
                    postconditions=postconditions,
                    source_line=source_line,
                )
            )
        return specs

def _is_rust_test_function(source: str, name: str) -> bool:
    """True when ``fn <name>`` is preceded by a Rust test attribute.

    Matches ``#[test]``, ``#[tokio::test]``, ``#[test_log::test]`` and similar
    attribute macros whose name ends with ``test``.
    """
    return bool(
        re.search(
            r"(?:#\s*\[[\s\S]*?test[\s\S]*?\]\s*){1,3}\s*(?:\b(?:async|const|unsafe)\b\s+)*fn\s+"
            + re.escape(name)
            + r"\b",
            source,
            re.IGNORECASE,
        )
    )


def _source_has_function_declarations(source: str, language: str) -> bool | None:
    """Return True when ``source`` contains at least one function declaration.

    ``None`` means the check was inconclusive (e.g., unsupported language or
    unparseable source); callers should treat ``None`` as "could have functions".
    """
    normalized = _normalize_language(language)
    if normalized == "go" and (_is_go_experimental(source) or _is_go_compiler_test(source)):
        return False
    if normalized in tree_sitter_extract.SUPPORTED_LANGUAGES:
        names = tree_sitter_extract.function_names(source, normalized, _safe_identifier)
        if names is not None:
            if normalized == "go":
                names = [name for name in names if not _is_go_test_name(name)]
            if normalized == "rust":
                names = [name for name in names if not _is_rust_test_function(source, name)]
            return bool(names)

    if normalized == "python":
        try:
            tree = ast.parse(source)
            return any(
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                for node in ast.walk(tree)
            )
        except SyntaxError:
            return None

    patterns = {
        "go": re.compile(r"\bfunc\s+[A-Za-z_]\w*"),
        "rust": re.compile(r"\bfn\s+[A-Za-z_]\w*"),
        "typescript": re.compile(r"\bfunction\s+[A-Za-z_]\w*"),
        "solidity": re.compile(r"\bfunction\s+[A-Za-z_]\w*"),
    }
    pattern = patterns.get(normalized)
    if pattern is not None:
        return bool(pattern.search(source))
    return None


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

    def verify(
        self, source_code: str, language: str, source_file: str | None = None
    ) -> dict[str, object]:
        normalized_language = _normalize_language(language)
        specs = self.extractor.extract(source_code, normalized_language)
        safety_issues = _filter_covered_safety_issues(
            _detect_safety_issues(source_code, normalized_language, source_file=source_file),
            specs,
        )
        atoms = [to_mumei_atom(spec) for spec in specs]
        mumei_source = "\n\n".join(atoms) + ("\n" if atoms else "")
        if not specs:
            has_functions = _source_has_function_declarations(
                source_code, normalized_language
            )
            if has_functions is False and not safety_issues:
                return {
                    "success": True,
                    "language": normalized_language,
                    "specs": [],
                    "atoms": [],
                    "source_line_map": {},
                    "mumei_source": "",
                    "verification": {"success": True, "report": {"status": "verified"}},
                    "errors": [],
                    "warnings": [
                        "No function signatures were extracted; source contains no function declarations."
                    ],
                    **_first_counterexample_payload([]),
                }
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

        errors = [issue.message for issue in safety_issues]
        # A `trusted` / `satisfiable_with_skips` verify with no failed atoms and
        # no counterexample is inconclusive (an accepted proof hole), not an
        # actual code-safety failure, so it must not add "mumei verify failed".
        if not verification.get("success") and not _is_inconclusive_verify(verification):
            errors.append("mumei verify failed")
        return {
            "success": bool(verification.get("success")) and not safety_issues,
            "language": normalized_language,
            "specs": [asdict(spec) for spec in specs],
            "atoms": atoms,
            "source_line_map": {spec.function_name: spec.source_line for spec in specs},
            "mumei_source": mumei_source,
            "verification": verification,
            "errors": errors,
            "warnings": [],
            **_first_counterexample_payload(safety_issues),
        }

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
        help="Source language (python/typescript/rust/go/solidity).",
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
