"""Prompt/skeleton preprocessing helpers for generate strategy."""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

_logger = logging.getLogger(__name__)

_CORE_AXIOM_HEADER = "# Available Core Axioms (from std/core.mm)"

_TYPE_DEFINITION_RE = re.compile(
    r"^\s*type\s+[A-Za-z_][A-Za-z0-9_]*\s*=.*?;\s*$",
    re.MULTILINE,
)

_ATOM_SIGNATURE_RE = re.compile(
    r"^atom\s+[A-Za-z_][A-Za-z0-9_]*\s*\([^)]*\).*?"
    r"ensures\s*:[^;]*;",
    re.DOTALL | re.MULTILINE,
)

# Cache the rendered axiom summary keyed by ``(path, mtime)`` so
# repeated generations do not re-read disk.
_CORE_AXIOM_CACHE: dict[tuple[str, float], str] = {}

def _default_prompt_report_truncate_chars() -> int:
    try:
        from agent.config import AgentConfig

        return AgentConfig().prompt_report_truncate_chars
    except Exception:
        return 4000

def _is_std_module(spec: dict) -> bool:
    """Return ``True`` when the spec targets a ``std/`` module.

    Looks at any of ``output_path``, ``target_file``, ``module_name``,
    or ``name`` for a leading ``std/`` segment.  Module names like
    ``std/iter`` also qualify.
    """
    candidates: list[str] = []
    for key in ("output_path", "target_file", "module_name", "name"):
        value = spec.get(key)
        if isinstance(value, str) and value:
            candidates.append(value)
    for cand in candidates:
        normalised = cand.replace("\\", "/").lstrip("./")
        if normalised.startswith("std/"):
            return True
    return False

def _summarise_core_axioms(source: str) -> str:
    """Extract core axiom types + atom signatures from ``std/core.mm``.

    Strips ``body: { ... };`` blocks to keep the injected prompt small.
    """
    sections: list[str] = []

    types = [match.group(0).strip() for match in _TYPE_DEFINITION_RE.finditer(source)]
    if types:
        sections.append("\n".join(types))

    signatures: list[str] = []
    for match in _ATOM_SIGNATURE_RE.finditer(source):
        sig = re.sub(r"\s+", " ", match.group(0)).strip()
        # Close the signature cleanly (``...;`` already present from
        # the trailing ``ensures: ... ;`` capture).
        signatures.append(sig)
    if signatures:
        sections.append("\n".join(signatures))

    return "\n\n".join(sections).strip()

def _load_core_axiom_context(path: str | os.PathLike | None) -> str:
    """Return the rendered core-axiom prompt block, or ``""`` on failure.

    Silent fallback: when the path is missing or unreadable we return an
    empty string so generation continues without the extra context.
    """
    if not path:
        return ""
    try:
        file_path = Path(path).expanduser()
    except (TypeError, ValueError):
        return ""
    try:
        stat = file_path.stat()
    except OSError:
        _logger.info("core.mm not available at %s (skipping axiom injection)", path)
        return ""

    cache_key = (str(file_path), stat.st_mtime)
    cached = _CORE_AXIOM_CACHE.get(cache_key)
    if cached is not None:
        return cached

    try:
        source = file_path.read_text(encoding="utf-8")
    except OSError:
        _logger.warning("Failed to read %s for core-axiom injection", file_path)
        return ""

    summary = _summarise_core_axioms(source)
    if not summary:
        return ""

    rendered = (
        f"{_CORE_AXIOM_HEADER}\n"
        "# You SHOULD use these types and atoms instead of defining your own.\n"
        "# Import with: `import \"std/core\" as core;`\n"
        "```mumei\n"
        f"{summary}\n"
        "```"
    )
    _CORE_AXIOM_CACHE[cache_key] = rendered
    return rendered

def _build_core_axiom_context(spec: dict) -> str:
    """Return the core-axiom block for *spec*, or ``""`` if not applicable.

    Honors the ``inject_core_axioms`` flag and ``core_axiom_path`` on the
    provided ``AgentConfig`` instance (or falls back to env vars when
    no config is threaded through).  The block is only returned for
    ``std/``-targeted specs so non-stdlib generations stay untouched.
    """
    if not _is_std_module(spec):
        return ""

    # Late import to avoid a circular import: config imports dotenv/openai
    # at module load, which is otherwise heavy for unit tests.
    try:
        from agent.config import AgentConfig, _default_core_axiom_path
    except ImportError:  # pragma: no cover - defensive
        return ""

    config = spec.get("_agent_config")
    if isinstance(config, AgentConfig):
        if not config.inject_core_axioms:
            return ""
        path = config.core_axiom_path
    else:
        if os.getenv("INJECT_CORE_AXIOMS", "true").lower() in {"false", "0", "no", "off"}:
            return ""
        path = _default_core_axiom_path()

    return _load_core_axiom_context(path)

def _extract_code(content: str) -> str:
    """Extract code from markdown fences or return raw content."""
    code_match = re.search(r'```\w*\s*\n(.*?)```', content, re.DOTALL)
    if code_match:
        return code_match.group(1).strip()
    return content.strip()

def _has_effects(spec: dict) -> bool:
    """Check whether the spec describes an atom with effects."""
    effects = spec.get("effects", [])
    return bool(effects)

def _select_prompt_module(spec: dict):
    """Select the appropriate prompt module based on the spec."""
    if _has_effects(spec):
        from agent.prompts import generate_stdlib
        return generate_stdlib
    from agent.prompts import generate_atom
    return generate_atom

def _build_skeleton(spec: dict) -> str:
    """Build an atom skeleton from a spec for the LLM to fill in."""
    name = spec.get("name", "unnamed")
    raw_params = spec.get("inputs", spec.get("params", []))
    if not isinstance(raw_params, list):
        raw_params = []
    params = ", ".join(
        f"{p['name']}: {p.get('type', 'i64')}"
        for p in raw_params
    )
    effects = spec.get("effects", [])
    effects_str = f"    effects: [{', '.join(effects)}]\n" if effects else ""
    return_type = spec.get("return_type")
    signature_return = f" -> {return_type}" if return_type else ""
    return (
        f"atom {name}({params}){signature_return}\n"
        f"{effects_str}"
        f"    requires: ___;\n"
        f"    ensures: ___;\n"
        f"    body: {{ ___ }}\n"
    )

def _detect_dependencies(atoms: list[dict]) -> dict[str, list[str]]:
    """Detect inter-atom dependencies within a multi-atom spec.

    Returns a mapping from atom name to a list of atom names it depends on
    (i.e. other atoms in the spec whose names appear in this atom's
    requires/ensures/description fields).

    Uses word-boundary matching to avoid false positives (e.g. atom
    ``div`` should not match the word ``division``).
    """
    atom_names = {a["name"] for a in atoms}
    deps: dict[str, list[str]] = {}
    for atom in atoms:
        name = atom["name"]
        # Collect text fields where references might appear
        searchable = " ".join(
            str(atom.get(k, ""))
            for k in ("requires", "ensures", "description")
        )
        deps[name] = [
            other for other in atom_names
            if other != name
            and re.search(r'\b' + re.escape(other) + r'\b', searchable)
        ]
    return deps

def _build_multi_atom_prompt(
    atoms: list[dict],
    deps: dict[str, list[str]],
) -> str:
    """Build a combined skeleton prompt for multiple atoms.

    If atom B depends on atom A, A's contract is included as context
    in B's skeleton section.
    """
    sections: list[str] = []
    # Build a lookup for quick access to atom specs by name
    by_name = {a["name"]: a for a in atoms}

    for atom in atoms:
        name = atom["name"]
        skeleton = _build_skeleton(atom)

        dep_context = ""
        for dep_name in deps.get(name, []):
            dep_atom = by_name[dep_name]
            dep_context += (
                f"// Dependency: {dep_name} — "
                f"requires: {dep_atom.get('requires', 'true')}, "
                f"ensures: {dep_atom.get('ensures', 'true')}\n"
            )

        section = ""
        if dep_context:
            section += f"# Context for {name}:\n{dep_context}\n"
        section += f"# Atom: {name}\n{skeleton}"
        sections.append(section)

    return "\n\n".join(sections)

def _identify_failing_atoms(
    report: dict,
    atom_names: list[str],
) -> list[str]:
    """Identify which atoms failed from a verification report.

    Falls back to returning all atom names if the failing atom cannot be
    determined from the report.
    """
    failing: list[str] = []
    # The report may contain a single "atom" field or a list of "atoms"
    report_atom = report.get("atom", "")
    report_atoms = report.get("atoms", [])

    if report_atom and report_atom in atom_names:
        failing.append(report_atom)
    for ra in report_atoms:
        name = ra if isinstance(ra, str) else ra.get("name", "")
        if name in atom_names:
            failing.append(name)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for f in failing:
        if f not in seen:
            seen.add(f)
            unique.append(f)

    return unique if unique else list(atom_names)
