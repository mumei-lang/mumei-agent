"""Rust to Mumei DSL transpiler."""
from __future__ import annotations

import re
from pathlib import Path

from agent.config import AgentConfig
from agent.transpiler import TranspileResult


class RustTranspiler:
    """Transpile Rust code to Mumei DSL."""

    _FUNCTION_PATTERN = re.compile(
        r"(?:pub(?:\s*\([^)]*\))?\s+)?fn\s+"
        r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*"
        r"(?:<[^>{}]*>)?\s*"
        r"\((?P<params>[^)]*)\)\s*"
        r"(?:->\s*(?P<return_type>[^{\n]+?))?\s*"
        r"\{(?P<body>.*?)\n\}",
        re.DOTALL,
    )

    def __init__(self, config: AgentConfig):
        self.config = config

    def transpile_file(
        self,
        input_path: Path,
        output_path: Path | None = None,
    ) -> TranspileResult:
        """Transpile a Rust file to Mumei DSL."""
        try:
            code = input_path.read_text(encoding="utf-8")
        except OSError as exc:
            return TranspileResult(
                success=False,
                mumei_code="",
                warnings=[],
                errors=[f"Failed to read {input_path}: {exc}"],
            )

        functions = self._extract_functions(code)
        warnings = []
        if not functions:
            warnings.append(f"No Rust functions found in {input_path}")

        atoms = [self._function_to_atom(func) for func in functions]
        mumei_code = self._generate_mm_file(atoms)

        if output_path:
            try:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(mumei_code, encoding="utf-8")
            except OSError as exc:
                return TranspileResult(
                    success=False,
                    mumei_code=mumei_code,
                    warnings=warnings,
                    errors=[f"Failed to write {output_path}: {exc}"],
                )

        return TranspileResult(
            success=True,
            mumei_code=mumei_code,
            warnings=warnings,
            errors=[],
        )

    def _extract_functions(self, code: str) -> list[dict[str, object]]:
        """Extract function signatures from Rust code."""
        functions: list[dict[str, object]] = []
        for match in self._FUNCTION_PATTERN.finditer(self._strip_comments(code)):
            return_type = (match.group("return_type") or "()").strip()
            functions.append(
                {
                    "name": match.group("name"),
                    "params": self._parse_params(match.group("params")),
                    "return_type": return_type,
                    "body": match.group("body").strip(),
                }
            )
        return functions

    def _parse_params(self, params_str: str) -> list[dict[str, str]]:
        """Parse function parameters."""
        params = []
        for param in self._split_top_level(params_str, ","):
            param = param.strip()
            if not param or param in {"self", "&self", "&mut self"}:
                continue
            if ":" in param:
                name, typ = param.split(":", 1)
                params.append({"name": name.strip(), "type": typ.strip()})
        return params

    def _function_to_atom(self, func: dict[str, object]) -> str:
        """Convert a Rust function to Mumei atom."""
        params = func["params"]
        if not isinstance(params, list):
            params = []
        requires = self._infer_requires(str(func["body"]))
        ensures = self._infer_ensures()

        params_str = ", ".join(
            f"{p['name']}: {self._map_type(p['type'])}"
            for p in params
            if isinstance(p, dict)
        )
        return_type = self._map_type(str(func["return_type"]))
        body = self._translate_body(str(func["body"]), return_type)

        return (
            f"atom {func['name']}({params_str}) -> {return_type}\n"
            f"    requires: {requires};\n"
            f"    ensures: {ensures};\n"
            "    body: {\n"
            f"        {body}\n"
            "    };"
        )

    def _infer_requires(self, body: str) -> str:
        """Infer requires clause from assert! statements."""
        assertions = []
        for match in re.finditer(r"assert!\s*\((?P<expr>[^;]+?)\)\s*;", body):
            expr = match.group("expr").split(",", 1)[0].strip()
            assertions.append(self._translate_expr(expr))
        return " && ".join(assertions) if assertions else "true"

    def _infer_ensures(self) -> str:
        """Infer ensures clause from function logic."""
        return "true"

    def _map_type(self, rust_type: str) -> str:
        """Map Rust types to Mumei types."""
        cleaned = rust_type.strip().removesuffix(";")
        cleaned = cleaned.replace("&'static str", "&str")
        cleaned = cleaned.replace("& str", "&str")
        type_map = {
            "()": "Unit",
            "i8": "i64",
            "i16": "i64",
            "i32": "i64",
            "i64": "i64",
            "isize": "i64",
            "u8": "u64",
            "u16": "u64",
            "u32": "u64",
            "u64": "u64",
            "usize": "u64",
            "f32": "f64",
            "f64": "f64",
            "bool": "bool",
            "String": "Str",
            "&str": "Str",
        }
        return type_map.get(cleaned, cleaned)

    def _generate_mm_file(self, atoms: list[str]) -> str:
        """Generate .mm file content."""
        header = "// Auto-generated from Rust code by mumei-agent transpiler"
        if not atoms:
            return f"{header}\n"
        return header + "\n\n" + "\n\n".join(atoms) + "\n"

    def _translate_body(self, body: str, return_type: str) -> str:
        statements = [
            line.strip()
            for line in body.splitlines()
            if line.strip() and not line.strip().startswith("assert!")
        ]
        if not statements:
            return self._default_value(return_type)
        expr = statements[-1]
        if expr.startswith("return "):
            expr = expr[len("return "):]
        return self._translate_expr(expr.rstrip(";"))

    def _translate_expr(self, expr: str) -> str:
        return (
            expr.replace("&&", "&&")
            .replace("||", "||")
            .replace("true", "true")
            .replace("false", "false")
            .strip()
        )

    def _default_value(self, return_type: str) -> str:
        if return_type in {"i64", "u64", "f64"}:
            return "0"
        if return_type == "bool":
            return "false"
        if return_type == "Str":
            return '""'
        return "unit"

    def _strip_comments(self, code: str) -> str:
        code = re.sub(r"//.*", "", code)
        return re.sub(r"/\*.*?\*/", "", code, flags=re.DOTALL)

    def _split_top_level(self, text: str, delimiter: str) -> list[str]:
        parts = []
        current = []
        depth = 0
        for char in text:
            if char in "(<[":
                depth += 1
            elif char in ")>]":
                depth = max(0, depth - 1)
            if char == delimiter and depth == 0:
                parts.append("".join(current))
                current = []
            else:
                current.append(char)
        parts.append("".join(current))
        return parts
