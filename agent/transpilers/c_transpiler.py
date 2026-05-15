"""C to Mumei DSL transpiler."""
from __future__ import annotations

import re
from pathlib import Path

from agent.config import AgentConfig
from agent.transpiler import TranspileResult


class CTranspiler:
    """Transpile C code to Mumei DSL."""

    _FUNCTION_PATTERN = re.compile(
        r"(?P<return_type>[A-Za-z_][A-Za-z0-9_\s\*]*?)\s+"
        r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*"
        r"\((?P<params>[^)]*)\)\s*"
        r"\{(?P<body>.*?)\n\}",
        re.DOTALL,
    )
    _CONTROL_KEYWORDS = {"if", "for", "while", "switch"}

    def __init__(self, config: AgentConfig):
        self.config = config

    def transpile_file(
        self,
        input_path: Path,
        output_path: Path | None = None,
    ) -> TranspileResult:
        """Transpile a C file to Mumei DSL."""
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
            warnings.append(f"No C functions found in {input_path}")

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
        """Extract function signatures from C code."""
        functions: list[dict[str, object]] = []
        for match in self._FUNCTION_PATTERN.finditer(self._strip_comments(code)):
            name = match.group("name")
            if name in self._CONTROL_KEYWORDS:
                continue
            functions.append(
                {
                    "return_type": self._normalize_c_type(match.group("return_type")),
                    "name": name,
                    "params": self._parse_params(match.group("params")),
                    "body": match.group("body").strip(),
                }
            )
        return functions

    def _parse_params(self, params_str: str) -> list[dict[str, str]]:
        """Parse function parameters."""
        params = []
        stripped = params_str.strip()
        if not stripped or stripped == "void":
            return params
        for param in params_str.split(","):
            param = self._normalize_c_type(param)
            if not param or " " not in param:
                continue
            typ, name = param.rsplit(" ", 1)
            pointer_prefix = ""
            while name.startswith("*"):
                pointer_prefix += "*"
                name = name[1:]
            array_suffix = ""
            if "[" in name:
                name = name.split("[", 1)[0]
                array_suffix = "*"
            params.append(
                {
                    "name": name.strip(),
                    "type": self._normalize_c_type(f"{typ}{pointer_prefix}{array_suffix}"),
                }
            )
        return params

    def _function_to_atom(self, func: dict[str, object]) -> str:
        """Convert a C function to Mumei atom."""
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
        """Infer requires clause from assert statements."""
        assertions = []
        for match in re.finditer(r"assert\s*\((?P<expr>[^;]+?)\)\s*;", body):
            assertions.append(self._translate_expr(match.group("expr")))
        return " && ".join(assertions) if assertions else "true"

    def _infer_ensures(self) -> str:
        """Infer ensures clause from function logic."""
        return "true"

    def _map_type(self, c_type: str) -> str:
        """Map C types to Mumei types."""
        cleaned = self._normalize_c_type(c_type)
        type_map = {
            "void": "Unit",
            "int": "i64",
            "short": "i64",
            "short int": "i64",
            "long": "i64",
            "long int": "i64",
            "long long": "i64",
            "long long int": "i64",
            "signed": "i64",
            "signed int": "i64",
            "unsigned": "u64",
            "unsigned int": "u64",
            "unsigned long": "u64",
            "unsigned long int": "u64",
            "unsigned long long": "u64",
            "unsigned long long int": "u64",
            "float": "f64",
            "double": "f64",
            "bool": "bool",
            "_Bool": "bool",
            "char": "Str",
            "char*": "Str",
            "const char*": "Str",
            "char *": "Str",
            "const char *": "Str",
        }
        return type_map.get(cleaned, cleaned)

    def _generate_mm_file(self, atoms: list[str]) -> str:
        """Generate .mm file content."""
        header = "// Auto-generated from C code by mumei-agent transpiler"
        if not atoms:
            return f"{header}\n"
        return header + "\n\n" + "\n\n".join(atoms) + "\n"

    def _translate_body(self, body: str, return_type: str) -> str:
        returns = re.findall(r"\breturn\s+(?P<expr>[^;]+);", body)
        if returns:
            return self._translate_expr(returns[-1])
        return self._default_value(return_type)

    def _translate_expr(self, expr: str) -> str:
        return expr.strip()

    def _default_value(self, return_type: str) -> str:
        if return_type in {"i64", "u64", "f64"}:
            return "0"
        if return_type == "bool":
            return "false"
        if return_type == "Str":
            return '""'
        return "unit"

    def _normalize_c_type(self, c_type: str) -> str:
        cleaned = " ".join(c_type.strip().split())
        cleaned = cleaned.replace(" *", "*").replace("* ", "*")
        for qualifier in ("static ", "inline ", "extern ", "const "):
            if cleaned.startswith(qualifier) and not cleaned.startswith("const char"):
                cleaned = cleaned.removeprefix(qualifier)
        return cleaned

    def _strip_comments(self, code: str) -> str:
        code = re.sub(r"//.*", "", code)
        return re.sub(r"/\*.*?\*/", "", code, flags=re.DOTALL)
