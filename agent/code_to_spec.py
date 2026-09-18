"""Extract natural language specifications from existing source code."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol, cast

import chardet
from openai import OpenAI

from agent import telemetry
from agent.config import AgentConfig
from agent.llm_provider import LLMProvider
from agent.mumei_client import MumeiClient
from agent.prompts.code_to_spec import (
    CODE_TO_SPEC_SYSTEM_PROMPT,
    build_code_to_spec_prompt,
)
from agent.strategies.foreign_code_strategy_helpers import (
    _is_go_build_ignore,
    _is_go_compiler_test,
    _is_go_experimental,
    _is_go_test_helper,
)

logger = logging.getLogger(__name__)

#: Bump when the extraction prompt or spec-alignment logic changes so stale
#: cache entries are not mistaken for current output.
_SPEC_CACHE_SCHEMA_VERSION = 1


def _spec_cache_key(code: str, language: str, model: str, domain_hint: str) -> str:
    """Content-addressed key for one extract_from_file LLM result."""
    digest = hashlib.sha256()
    digest.update(str(_SPEC_CACHE_SCHEMA_VERSION).encode())
    digest.update(b"\x00")
    digest.update(model.encode())
    digest.update(b"\x00")
    digest.update(language.encode())
    digest.update(b"\x00")
    digest.update(domain_hint.encode())
    digest.update(b"\x00")
    digest.update(code.encode("utf-8", errors="replace"))
    return digest.hexdigest()


def _spec_cache_path(cache_dir: str, key: str) -> Path:
    return Path(cache_dir).expanduser() / f"{key}.json"


# Top-level declaration markers used by the function-splitting extractor.  A
# line at column 0 starting one of these begins a new chunk.
_FUNCTION_START_RES: dict[str, re.Pattern[str]] = {
    "go": re.compile(r"^func\b", re.MULTILINE),
    "rust": re.compile(r"^(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\b", re.MULTILINE),
    "python": re.compile(r"^(?:async\s+)?def\b|^class\b", re.MULTILINE),
    "typescript": re.compile(r"^(?:export\s+)?(?:async\s+)?function\b|^(?:export\s+)?class\b", re.MULTILINE),
    "javascript": re.compile(r"^(?:export\s+)?(?:async\s+)?function\b|^(?:export\s+)?class\b", re.MULTILINE),
    "solidity": re.compile(r"^\s*function\b|^\s*constructor\b|^contract\b", re.MULTILINE),
    "java": re.compile(r"^[ \t]*(?:public|private|protected|static|final|synchronized|\s)*\w[\w<>\[\]]*\s+\w+\s*\(", re.MULTILINE),
    "c": re.compile(r"^[A-Za-z_]\w*[\s*]+\w+\s*\(", re.MULTILINE),
    "cpp": re.compile(r"^[A-Za-z_]\w*[\s*:&<>]+\w+\s*\(", re.MULTILINE),
}


def _split_code_chunks(code: str, language: str, max_chars: int) -> list[str]:
    """Split ``code`` into per-function chunks capped near ``max_chars``.

    The preamble (package/imports/type decls before the first function) is
    prepended to every chunk so each split keeps namespace context.  Returns
    ``[]`` when the language has no boundary regex or no split point exists.
    """
    pattern = _FUNCTION_START_RES.get(language)
    if pattern is None:
        return []
    starts = sorted({match.start() for match in pattern.finditer(code)})
    if len(starts) < 2:
        return []
    preamble = code[: starts[0]]
    units = [code[a:b] for a, b in zip(starts, [*starts[1:], len(code)])]
    chunks: list[str] = []
    current = preamble
    for unit in units:
        if len(current) + len(unit) > max_chars and current != preamble:
            chunks.append(current)
            current = preamble + unit
        else:
            current += unit
    chunks.append(current)
    return [chunk for chunk in chunks if chunk.strip()]


def _merge_forge_task_specs(specs: list[dict]) -> dict | None:
    """Merge per-chunk forge task specs by concatenating unique atoms."""
    merged: dict | None = None
    seen: set[str] = set()
    for spec in specs:
        if not isinstance(spec, dict):
            continue
        if merged is None:
            merged = {**spec, "atoms": []}
        for atom in spec.get("atoms") or []:
            name = atom.get("name") if isinstance(atom, dict) else None
            if name is None or name in seen:
                continue
            seen.add(name)
            merged["atoms"].append(atom)
    if merged is not None and not merged["atoms"]:
        return None
    return merged


def _read_spec_cache(
    cache_dir: str, key: str
) -> tuple[str, dict | None] | None:
    """Return (natural_language_spec, forge_task_spec) on a cache hit."""
    try:
        payload = json.loads(
            _spec_cache_path(cache_dir, key).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    natural_language_spec = payload.get("natural_language_spec")
    if not isinstance(natural_language_spec, str) or not natural_language_spec:
        return None
    forge_task_spec = payload.get("forge_task_spec")
    if forge_task_spec is not None and not isinstance(forge_task_spec, dict):
        return None
    return natural_language_spec, forge_task_spec


def _write_spec_cache(
    cache_dir: str, key: str, natural_language_spec: str, forge_task_spec: dict | None
) -> None:
    path = _spec_cache_path(cache_dir, key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename keeps a killed run from leaving a truncated entry
        # that a later audit would read.
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(
                {
                    "natural_language_spec": natural_language_spec,
                    "forge_task_spec": forge_task_spec,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        tmp_path.replace(path)
    except OSError:
        logger.debug("Could not write spec cache at %s", path, exc_info=True)

Language = Literal[
    "rust",
    "c",
    "go",
    "python",
    "javascript",
    "typescript",
    "java",
    "cpp",
    "solidity",
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
        layer_b_languages = {"python", "rust", "typescript", "go", "solidity"}
        if normalized not in layer_b_languages:
            is_layer_a = normalized in set(CodeToSpecExtractor.EXTENSION_MAP.values())
            if is_layer_a:
                hint = (
                    f"'{normalized}' is supported for spec extraction (Layer A) "
                    f"but Z3 strict verification (Layer B) requires one of: "
                    f"{', '.join(sorted(layer_b_languages))}."
                )
            else:
                layer_a_only = sorted(
                    set(CodeToSpecExtractor.EXTENSION_MAP.values()) - layer_b_languages
                )
                hint = (
                    f"language must be one of: {', '.join(sorted(layer_b_languages))} "
                    f"(Z3 strict verification). "
                    f"Spec extraction (Layer A) also supports: "
                    f"{', '.join(layer_a_only)}."
                )
            return CodeToSpecConversionResult(
                success=False,
                atoms=[],
                natural_language_spec="",
                mumei_source="",
                detected_language=detected_language,
                errors=[hint],
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
        "sol": "solidity",
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


# ---------------------------------------------------------------------------
# Helpers for aligning LLM-extracted forge specs with deterministic source atoms
# ---------------------------------------------------------------------------

_GENERIC_NAME_TOKENS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being", "am",
    "has", "have", "had", "do", "does", "did", "can", "could", "will", "would",
    "shall", "should", "may", "might", "must", "and", "or", "not", "no", "yes",
    "any", "all", "each", "every", "some", "none", "to", "get", "set", "in", "on",
    "at", "by", "with", "from", "of", "for", "as", "into", "onto", "over", "under",
    "above", "below", "before", "after", "during", "through", "across", "around",
    "between", "among", "within", "without", "outside", "inside", "off", "out", "up",
    "down",
})


def _canonicalize_name(name: str) -> str:
    """Return a case- and underscore-insensitive key for matching symbol names."""
    return name.strip().replace("_", "").lower()


def _strip_safe_prefix(name: str) -> str | None:
    """Remove a leading ``safe_`` / ``Safe`` prefix from hallucinated atom names."""
    lowered = name.lower()
    if lowered.startswith("safe_"):
        return name[5:]
    if lowered.startswith("safe") and len(name) > 4 and name[4].isupper():
        rest = name[4:]
        return rest[0].lower() + rest[1:]
    return None


def _name_tokens(name: str) -> list[str]:
    """Split a camelCase / snake_case identifier into lowercase tokens."""
    spaced = re.sub(r"(?<!^)(?=[A-Z])", "_", name)
    return [t.lower() for t in re.split(r"[^A-Za-z0-9]+", spaced) if t and not t.isdigit()]


def _token_match(llm_token: str, source_token: str) -> bool:
    """True when two name tokens match exactly or one contains the other."""
    if llm_token == source_token:
        return True
    if len(llm_token) < 3 or len(source_token) < 3:
        return False
    return llm_token in source_token or source_token in llm_token


def _filtered_tokens(tokens: list[str]) -> list[str]:
    return [t for t in tokens if t not in _GENERIC_NAME_TOKENS and len(t) >= 2]


def _token_score(llm_name: str, source_name: str) -> int:
    """Score how many non-generic tokens of ``llm_name`` match ``source_name``."""
    llm_tokens = _filtered_tokens(_name_tokens(llm_name))
    source_tokens = _filtered_tokens(_name_tokens(source_name))
    if not llm_tokens:
        return 0
    score = 0
    for lt in llm_tokens:
        for st in source_tokens:
            if _token_match(lt, st):
                score += 1
                break
    return score


def _best_matching_source_atom(
    name: str,
    source_atoms: list[ContractLike],
    source_by_canon: dict[str, ContractLike],
) -> ContractLike | None:
    """Map an LLM atom name to the most likely deterministic source atom."""
    canon = _canonicalize_name(name)
    if canon in source_by_canon:
        return source_by_canon[canon]

    stripped = _strip_safe_prefix(name)
    if stripped is not None:
        canon = _canonicalize_name(stripped)
        if canon in source_by_canon:
            return source_by_canon[canon]

    if not source_atoms:
        return None

    candidate = stripped if stripped is not None else name
    llm_tokens = _filtered_tokens(_name_tokens(candidate))
    if not llm_tokens:
        return None
    threshold = max(1, (len(llm_tokens) + 1) // 2)
    best: ContractLike | None = None
    best_score = -1
    for source_atom in source_atoms:
        score = _token_score(candidate, source_atom.name)
        if score >= threshold and score > best_score:
            best_score = score
            best = source_atom
    return best


def _align_llm_spec_with_source(
    forge_task_spec: dict[str, object],
    source_atoms: list[ContractLike],
    code_path: Path,
    warnings: list[str],
) -> dict[str, object]:
    """Replace hallucinated LLM atom names with actual source function names.

    Atoms that cannot be matched to a source function are dropped, and source
    functions missing from the LLM spec are added from the deterministic parser.
    """
    if not isinstance(forge_task_spec, dict):
        return forge_task_spec

    atoms = forge_task_spec.get("atoms")
    if not isinstance(atoms, list):
        return forge_task_spec

    source_by_canon = {_canonicalize_name(atom.name): atom for atom in source_atoms}
    matched_by_canon: dict[str, dict[str, object]] = {}

    for atom in atoms:
        if not isinstance(atom, dict):
            continue
        name = atom.get("name", "")
        if not name or not isinstance(name, str):
            continue
        source_atom = _best_matching_source_atom(name, source_atoms, source_by_canon)
        if source_atom is None:
            warnings.append(
                f"Dropping spec atom '{name}' with no matching source function."
            )
            continue
        atom["name"] = source_atom.name
        canon = _canonicalize_name(source_atom.name)
        if canon in matched_by_canon:
            warnings.append(f"Duplicate spec atom mapping for '{source_atom.name}'.")
            continue
        matched_by_canon[canon] = atom

    final_atoms: list[dict[str, object]] = []
    for source_atom in source_atoms:
        canon = _canonicalize_name(source_atom.name)
        if canon in matched_by_canon:
            final_atoms.append(cast(dict[str, object], matched_by_canon[canon]))
        else:
            base = _forge_task_spec_from_atoms(code_path, [source_atom])
            final_atoms.extend(base["atoms"])

    forge_task_spec["atoms"] = final_atoms
    return forge_task_spec


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
        ".sol": "solidity",
    }

    def __init__(
        self,
        config: AgentConfig,
        client: object | None = None,
        *,
        llm_provider: LLMProvider | None = None,
    ):
        self.config = config
        if llm_provider is not None and client is None:
            from agent.llm_provider import openai_client_adapter

            client = openai_client_adapter(llm_provider)
        self._injected_client = client

    def _detect_language(self, code_path: Path, code: str) -> Language:
        """Detect the source language from file extension or code content."""
        suffix = code_path.suffix.lower()
        if suffix in self.EXTENSION_MAP:
            return self.EXTENSION_MAP[suffix]

        code_lower = code.lower()
        if "pragma solidity" in code_lower or re.search(r"\bcontract\s+[A-Z]", code):
            return "solidity"
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
        tracer = telemetry.get_tracer(__name__)
        with tracer.start_as_current_span("llm.code_to_spec") as span:
            span.set_attribute("gen_ai.system", "openai-compatible")
            span.set_attribute("gen_ai.request.model", self.config.model)
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

        # Skip Go compiler/test files that are not normal runnable code.
        if detected_language == "go" and (
            _is_go_compiler_test(code)
            or _is_go_experimental(code)
            or _is_go_test_helper(code)
            or _is_go_build_ignore(code)
            or code_path.name.endswith("_test.go")
            or re.search(r"(?:^|[/\\])go[/\\]test[/\\]", str(code_path)) is not None
            or re.search(r"(?:^|[/\\])testdata[/\\]", str(code_path)) is not None
        ):
            return CodeToSpecResult(
                success=True,
                natural_language_spec="",
                forge_task_spec=_forge_task_spec_from_atoms(code_path, []),
                detected_language=detected_language,
                warnings=["Skipped Go compiler/test/source file."],
                errors=[],
            )

        deterministic = CodeToSpecConverter(self.config).convert_source(
            code,
            detected_language,
        )
        # If the source contains no inferable functions (e.g. a struct-only
        # .sol file), skip the expensive LLM extraction and return an empty
        # spec so the audit pipeline can proceed without a "no atoms" error.
        if not deterministic.errors and not deterministic.atoms:
            warnings.extend(deterministic.warnings)
            warnings.append(
                "LLM extraction skipped because source contains no inferable functions."
            )
            return CodeToSpecResult(
                success=True,
                natural_language_spec=deterministic.natural_language_spec,
                forge_task_spec=_forge_task_spec_from_atoms(code_path, []),
                detected_language=detected_language,
                warnings=warnings,
                errors=[],
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

        cache_dir = self.config.spec_cache_dir
        cache_key = (
            _spec_cache_key(code, detected_language, self.config.model, domain_hint)
            if cache_dir
            else ""
        )
        if cache_dir:
            cached = _read_spec_cache(cache_dir, cache_key)
            if cached is not None:
                cached_spec, cached_forge_spec = cached
                warnings.append(
                    "Spec extraction served from cache "
                    f"(key {cache_key[:12]}); source unchanged."
                )
                return CodeToSpecResult(
                    success=True,
                    natural_language_spec=cached_spec,
                    forge_task_spec=cached_forge_spec,
                    detected_language=detected_language,
                    warnings=warnings,
                    errors=[],
                )

        try:
            client = self._injected_client or self.config.create_client()
            from agent.spec_extractor import extract_spec

            final_domain_hint = domain_hint or self._infer_domain(code, detected_language)
            split_chars = self.config.spec_split_chars
            chunks = (
                _split_code_chunks(code, detected_language, split_chars)
                if split_chars > 0 and len(code) > split_chars
                else []
            )
            if chunks:
                from concurrent.futures import ThreadPoolExecutor

                def _extract_chunk(chunk: str) -> tuple[str, dict | None]:
                    try:
                        nl = self._extract_spec_with_llm(
                            client, chunk, detected_language
                        ).strip()
                    except Exception as exc:  # keep other chunks' results
                        logger.debug("spec split chunk extraction failed: %s", exc)
                        return "", None
                    try:
                        spec = (
                            extract_spec(
                                client,
                                self.config.model,
                                nl,
                                domain_hint=final_domain_hint,
                                mumei_client=mumei_client,
                                max_retries=max_retries,
                            )
                            if nl
                            else None
                        )
                    except Exception as exc:
                        logger.debug("spec split chunk forge extraction failed: %s", exc)
                        spec = None
                    return nl, spec

                with ThreadPoolExecutor(max_workers=min(4, len(chunks))) as pool:
                    per_chunk = list(pool.map(_extract_chunk, chunks))
                natural_language_spec = "\n\n".join(
                    nl for nl, _ in per_chunk if nl
                )
                forge_task_spec = _merge_forge_task_specs(
                    [spec for _, spec in per_chunk if spec]
                )
                warnings.append(
                    f"Spec extraction split into {len(chunks)} function chunks "
                    f"(MUMEI_SPEC_SPLIT_CHARS={split_chars})."
                )
            else:
                natural_language_spec = self._extract_spec_with_llm(
                    client,
                    code,
                    detected_language,
                ).strip()
                forge_task_spec = None
            if not natural_language_spec:
                return CodeToSpecResult(
                    success=False,
                    natural_language_spec="",
                    forge_task_spec=None,
                    detected_language=detected_language,
                    warnings=warnings,
                    errors=["LLM returned an empty natural language specification"],
                )

            if forge_task_spec is None:
                forge_task_spec = extract_spec(
                    client,
                    self.config.model,
                    natural_language_spec,
                    domain_hint=final_domain_hint,
                    mumei_client=mumei_client,
                    max_retries=max_retries,
                )
            if forge_task_spec and not deterministic.errors:
                forge_task_spec = _align_llm_spec_with_source(
                    forge_task_spec,
                    deterministic.atoms,
                    code_path,
                    warnings,
                )
            if cache_dir:
                _write_spec_cache(
                    cache_dir, cache_key, natural_language_spec, forge_task_spec
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
