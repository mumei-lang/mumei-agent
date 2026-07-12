"""Pure regex-based extraction helpers for cross-validation strategy."""
from __future__ import annotations

import re
from typing import Any


def _canonical_symbol(name: str) -> str:
    """Canonicalize a symbol name for normalization-tolerant matching.

    Spec-atom names and source symbols come from different extractors that
    normalize casing/underscores differently (snake_case vs camelCase vs a
    leading ``_``). Comparing raw names yields false "no matching
    implementation" gaps, so both sides are reduced to a case- and
    underscore-insensitive key: ``_check_arg_length``, ``check_arg_length``
    and ``CheckArgLength`` all collapse to ``checkarglength``.
    """
    return name.strip().replace("_", "").lower()


# ---------------------------------------------------------------------------
# Implementation function extraction
# ---------------------------------------------------------------------------

_PYTHON_FUNC_RE = re.compile(
    r"^\s*(?:async\s+)?def\s+(\w+)\s*\(([^)]*)\)",
    re.MULTILINE,
)
_RUST_FUNC_RE = re.compile(
    r"(?:pub\s+)?(?:async\s+)?fn\s+(\w+)\s*(?:<[^>]*>)?\s*\(([^)]*)\)",
    re.MULTILINE,
)
_TS_FUNC_RE = re.compile(
    r"(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*(?:<[^>]*>)?\s*\(([^)]*)\)",
    re.MULTILINE,
)
_TS_ARROW_RE = re.compile(
    # Allow an optional type annotation between the name and `=`, e.g.
    # `export const timingSafeEqual: TimingSafeEqual = async (...) => ...`.
    r"(?:export\s+)?(?:const|let)\s+(\w+)\s*(?::\s*[^=;]+?)?\s*=\s*(?:async\s+)?\(",
    re.MULTILINE,
)
_GO_FUNC_RE = re.compile(
    r"func\s+(\w+)\s*\(([^)]*)\)",
    re.MULTILINE,
)


def _extract_functions(source: str, language: str) -> list[str]:
    """Extract top-level function names from implementation source."""
    lang = language.strip().lower()
    if lang == "python":
        return [m.group(1) for m in _PYTHON_FUNC_RE.finditer(source)]
    if lang == "rust":
        return [m.group(1) for m in _RUST_FUNC_RE.finditer(source)]
    if lang in ("typescript", "ts", "javascript", "js"):
        names = [m.group(1) for m in _TS_FUNC_RE.finditer(source)]
        names.extend(m.group(1) for m in _TS_ARROW_RE.finditer(source))
        return names
    if lang == "go":
        return [m.group(1) for m in _GO_FUNC_RE.finditer(source)]
    return []


# ---------------------------------------------------------------------------
# Spec atom extraction from .mm
# ---------------------------------------------------------------------------

_ATOM_DEF_RE = re.compile(
    r"atom\s+(\w+)\s*\(([^)]*)\)",
    re.MULTILINE,
)
_REQUIRES_RE = re.compile(r"requires\s*:\s*(.+?)(?:\n|ensures|effects|\{)", re.DOTALL)
_ENSURES_RE = re.compile(r"ensures\s*:\s*(.+?)(?:\n|effects|\{)", re.DOTALL)


def _extract_spec_atoms(spec_source: str) -> list[dict[str, Any]]:
    """Extract atom name, params, requires, ensures from .mm source."""
    atoms: list[dict[str, Any]] = []
    # Split on atom definitions to handle multi-atom files
    parts = re.split(r"(?=atom\s+\w+)", spec_source)
    for part in parts:
        m = _ATOM_DEF_RE.search(part)
        if not m:
            continue
        name = m.group(1)
        params_raw = m.group(2).strip()
        params = [p.strip().split(":")[0].strip() for p in params_raw.split(",") if p.strip()]
        req_m = _REQUIRES_RE.search(part)
        ens_m = _ENSURES_RE.search(part)
        atoms.append({
            "name": name,
            "params": params,
            "requires": req_m.group(1).strip() if req_m else "",
            "ensures": ens_m.group(1).strip() if ens_m else "",
        })
    return atoms


def _extract_function_body(source: str, language: str, function_name: str) -> str:
    escaped = re.escape(function_name)
    lang = language.strip().lower()
    patterns: list[re.Pattern[str]] = []
    if lang == "python":
        patterns.append(
            re.compile(
                rf"def\s+{escaped}\s*\([^)]*\):(?P<body>[\s\S]*?)(?=^\s*def\s+\w|\Z)",
                re.MULTILINE,
            )
        )
    elif lang == "rust":
        patterns.append(
            re.compile(
                rf"(?:pub\s+)?(?:async\s+)?fn\s+{escaped}\s*(?:<[^>]*>)?\s*\([^)]*\)[^\{{]*\{{(?P<body>[\s\S]*?)\}}",
                re.MULTILINE,
            )
        )
    elif lang in {"typescript", "ts", "javascript", "js"}:
        patterns.extend(
            [
                re.compile(
                    rf"(?:export\s+)?(?:async\s+)?function\s+{escaped}\s*(?:<[^>]*>)?\s*\([^)]*\)[^\{{]*\{{(?P<body>[\s\S]*?)\}}",
                    re.MULTILINE,
                ),
                re.compile(
                    # Allow an optional type annotation between the name and
                    # `=` (mirrors _TS_ARROW_RE) so bodies of declarations like
                    # `export const timingSafeEqual: TimingSafeEqual = async (...) => ...`
                    # are still analyzed for semantic gaps.
                    rf"(?:export\s+)?(?:const|let)\s+{escaped}\s*(?::\s*[^=;]+?)?\s*=\s*(?:async\s+)?\([^)]*\)\s*(?::[^=]+)?=>\s*(?P<body>\{{[\s\S]*?\}}|[^;\n]+)",
                    re.MULTILINE,
                ),
            ]
        )
    elif lang == "go":
        patterns.append(
            re.compile(
                rf"func\s+{escaped}\s*\([^)]*\)[^\{{]*\{{(?P<body>[\s\S]*?)\}}",
                re.MULTILINE,
            )
        )
    for pattern in patterns:
        match = pattern.search(source)
        if match:
            return match.group("body")
    return ""
