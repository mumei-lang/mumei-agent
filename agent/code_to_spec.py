"""Extract natural language specifications from existing source code."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

import chardet
from openai import OpenAI

from agent.config import AgentConfig
from agent.mumei_client import MumeiClient
from agent.prompts.code_to_spec import (
    CODE_TO_SPEC_SYSTEM_PROMPT,
    build_code_to_spec_prompt,
)

Language = Literal[
    "rust",
    "c",
    "go",
    "python",
    "javascript",
    "typescript",
    "java",
    "cpp",
    "unknown",
]


@dataclass
class CodeToSpecResult:
    """Result of code-to-spec extraction."""

    success: bool
    natural_language_spec: str
    forge_task_spec: dict | None
    detected_language: Language
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class ContractLike(Protocol):
    name: str
    requires: str
    ensures: str


@dataclass
class CodeToSpecConversionResult:
    """Deterministic code-to-contract conversion used by cross-validation."""

    success: bool
    atoms: list[ContractLike]
    natural_language_spec: str
    mumei_source: str
    detected_language: Language
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class CodeToSpecConverter:
    """Convert foreign-language code into Mumei contract atoms for verifier checks."""

    def __init__(self, config: AgentConfig | None = None):
        self.config = config or AgentConfig()

    def convert_source(self, code: str, language: str) -> CodeToSpecConversionResult:
        normalized = _normalize_language_name(language)
        supported_languages = set(CodeToSpecExtractor.EXTENSION_MAP.values())
        detected_language: Language = (
            normalized if normalized in supported_languages else "unknown"
        )
        if normalized not in {"python", "rust", "typescript", "go"}:
            return CodeToSpecConversionResult(
                success=False,
                atoms=[],
                natural_language_spec="",
                mumei_source="",
                detected_language=detected_language,
                errors=["language must be one of: python, rust, typescript, go"],
            )
        try:
            from agent.cross_validation import (
                _atoms_to_mumei_module,
                _infer_foreign_contracts_with_patterns,
            )

            atoms = _infer_foreign_contracts_with_patterns(code, normalized)
            return CodeToSpecConversionResult(
                success=bool(atoms),
                atoms=atoms,
                natural_language_spec=_atoms_to_natural_language(atoms),
                mumei_source=_atoms_to_mumei_module(atoms),
                detected_language=detected_language,
                warnings=[] if atoms else ["No functions were inferable from the input code."],
                errors=[],
            )
        except Exception as exc:
            return CodeToSpecConversionResult(
                success=False,
                atoms=[],
                natural_language_spec="",
                mumei_source="",
                detected_language=detected_language,
                errors=[str(exc)],
            )


def _atoms_to_natural_language(atoms: list[ContractLike]) -> str:
    lines: list[str] = []
    for atom in atoms:
        lines.append(f"{atom.name}: requires {atom.requires}; ensures {atom.ensures}.")
    return "\n".join(lines)


def _normalize_language_name(language: str) -> str:
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


def _forge_task_spec_from_atoms(
    code_path: Path,
    atoms: list[ContractLike],
) -> dict[str, object]:
    safe_stem = code_path.stem.replace("-", "_")
    return {
        "task_id": f"code-{safe_stem}",
        "target_file": f"audit/{safe_stem}.mm",
        "mode": "create",
        "atoms": [
            {
                "name": atom.name,
                "inputs": [
                    {"name": param.name, "type": param.type}
                    for param in getattr(atom, "params", [])
                ],
                "return_type": atom.return_type,
                "requires": atom.requires,
                "ensures": atom.ensures,
                "effects": list(getattr(atom, "effects", [])),
            }
            for atom in atoms
        ],
    }


class CodeToSpecExtractor:
    """Extract natural language specifications from existing code."""

    EXTENSION_MAP: dict[str, Language] = {
        ".rs": "rust",
        ".c": "c",
        ".h": "c",
        ".go": "go",
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".java": "java",
        ".cpp": "cpp",
        ".cc": "cpp",
        ".cxx": "cpp",
        ".hpp": "cpp",
    }

    def __init__(self, config: AgentConfig, client: object | None = None):
        self.config = config
        self._injected_client = client

    def _detect_language(self, code_path: Path, code: str) -> Language:
        """Detect the source language from file extension or code content."""
        suffix = code_path.suffix.lower()
        if suffix in self.EXTENSION_MAP:
            return self.EXTENSION_MAP[suffix]

        code_lower = code.lower()
        if "fn main()" in code or "fn " in code or "impl " in code:
            return "rust"
        if "#include" in code and ("int main" in code or "void " in code):
            return "c"
        if "package main" in code and "func " in code:
            return "go"
        if "def " in code or "import " in code_lower or "from " in code_lower:
            return "python"
        if "interface " in code and (": " in code or "type " in code):
            return "typescript"
        if "function " in code or "const " in code or "let " in code:
            return "javascript"
        if "public static void main" in code or "class " in code:
            return "java"
        if "#include" in code and ("std::" in code or "namespace " in code):
            return "cpp"
        return "unknown"

    def _extract_spec_with_llm(self, client: OpenAI, code: str, language: str) -> str:
        """Use an LLM to extract a natural language specification."""
        prompt = build_code_to_spec_prompt(code, language)
        response = client.chat.completions.create(
            model=self.config.model,
            messages=[
                {"role": "system", "content": CODE_TO_SPEC_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content or ""

    def _infer_domain(self, code: str, language: str) -> str:
        """Infer the extraction domain from source code identifiers."""
        code_lower = code.lower()
        if any(word in code_lower for word in ("balance", "transfer", "payment", "debit", "credit")):
            return "financial"
        if any(word in code_lower for word in ("encrypt", "decrypt", "hash", "signature", "rsa")):
            return "crypto"
        if any(word in code_lower for word in ("queue", "stack", "list", "push", "pop", "enqueue")):
            return "data_structure"
        if any(word in code_lower for word in ("sqrt", "pow", "sin", "cos", "abs")):
            return "math"
        if any(word in code_lower for word in ("auth", "token", "permission", "sanitize")):
            return "security"
        return ""

    def extract_from_file(
        self,
        code_path: Path,
        language: Language | None = None,
        *,
        domain_hint: str = "",
        mumei_client: MumeiClient | None = None,
        max_retries: int = 3,
    ) -> CodeToSpecResult:
        """Extract a natural language spec from source code and build a forge spec."""
        if not self.config.enable_code_to_spec:
            return CodeToSpecResult(
                success=False,
                natural_language_spec="",
                forge_task_spec=None,
                detected_language="unknown",
                errors=["code-to-spec extraction is disabled by AgentConfig"],
            )

        if not code_path.exists():
            return CodeToSpecResult(
                success=False,
                natural_language_spec="",
                forge_task_spec=None,
                detected_language="unknown",
                errors=[f"File not found: {code_path}"],
            )
        if not code_path.is_file():
            return CodeToSpecResult(
                success=False,
                natural_language_spec="",
                forge_task_spec=None,
                detected_language="unknown",
                errors=[f"Path is not a file: {code_path}"],
            )

        natural_language_spec = ""
        try:
            raw_bytes = code_path.read_bytes()
        except OSError as exc:
            return CodeToSpecResult(
                success=False,
                natural_language_spec="",
                forge_task_spec=None,
                detected_language="unknown",
                errors=[f"Failed to read file: {exc}"],
            )
        detected = chardet.detect(raw_bytes)
        detected_encoding = detected.get("encoding") or "utf-8"
        try:
            code = raw_bytes.decode(detected_encoding)
        except (UnicodeDecodeError, LookupError):
            code = raw_bytes.decode("utf-8", errors="replace")

        detected_language = _normalize_language_name(
            str(language or self._detect_language(code_path, code))
        )
        warnings: list[str] = []
        if detected_language == "unknown":
            warnings.append("language could not be detected; using generic code analysis")

        deterministic = CodeToSpecConverter(self.config).convert_source(
            code,
            detected_language,
        )
        if deterministic.success and not self.config.api_key and self._injected_client is None:
            warnings.extend(deterministic.warnings)
            warnings.append("LLM extraction skipped because LLM_API_KEY/OPENAI_API_KEY is not set.")
            return CodeToSpecResult(
                success=True,
                natural_language_spec=deterministic.natural_language_spec,
                forge_task_spec=_forge_task_spec_from_atoms(
                    code_path,
                    deterministic.atoms,
                ),
                detected_language=detected_language,
                warnings=warnings,
                errors=[],
            )

        try:
            client = self._injected_client or self.config.create_client()
            natural_language_spec = self._extract_spec_with_llm(
                client,
                code,
                detected_language,
            ).strip()
            if not natural_language_spec:
                return CodeToSpecResult(
                    success=False,
                    natural_language_spec="",
                    forge_task_spec=None,
                    detected_language=detected_language,
                    warnings=warnings,
                    errors=["LLM returned an empty natural language specification"],
                )

            from agent.spec_extractor import extract_spec

            final_domain_hint = domain_hint or self._infer_domain(code, detected_language)
            forge_task_spec = extract_spec(
                client,
                self.config.model,
                natural_language_spec,
                domain_hint=final_domain_hint,
                mumei_client=mumei_client,
                max_retries=max_retries,
            )
            return CodeToSpecResult(
                success=True,
                natural_language_spec=natural_language_spec,
                forge_task_spec=forge_task_spec,
                detected_language=detected_language,
                warnings=warnings,
                errors=[],
            )
        except Exception as exc:
            if deterministic.success:
                warnings.extend(deterministic.warnings)
                warnings.append(f"LLM extraction failed; used deterministic code parser: {exc}")
                return CodeToSpecResult(
                    success=True,
                    natural_language_spec=deterministic.natural_language_spec,
                    forge_task_spec=_forge_task_spec_from_atoms(
                        code_path,
                        deterministic.atoms,
                    ),
                    detected_language=detected_language,
                    warnings=warnings,
                    errors=[],
                )
            return CodeToSpecResult(
                success=False,
                natural_language_spec=natural_language_spec,
                forge_task_spec=None,
                detected_language=detected_language,
                warnings=warnings,
                errors=[str(exc)],
            )
