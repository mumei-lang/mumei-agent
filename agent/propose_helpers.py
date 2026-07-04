"""Seam-free pure helpers for the Phase 2-A forge task proposer.

These are the slug/import normalization, spec-shaping, summary, and
file-IO utilities extracted verbatim from :mod:`agent.propose`.  They
read no patched collaborators and touch no module-global
``subprocess`` / ``shutil`` seams, so they live here while the driver
(``main``), the CLI parser builder (``build_parser``), and the
MCP-backed loader (``_load_gaps_from_mcp`` — patched in the gap-rules
tests and lazily importing ``mcp_server``) remain in the façade.

This module must never import from :mod:`agent.propose`.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

# Scale LLM retry budget by human-authored difficulty hints.
_DIFFICULTY_RETRIES: dict[str, int] = {
    "low": 3,
    "medium": 5,
    "high": 8,
}

# Conservative task-id slug validator.  Forge task ids flow into git
# commit messages, so keep them to a safe charset.
_SLUG_RE = re.compile(r"[^a-z0-9_-]+")


def _module_to_slug(module_path: str) -> str:
    """Turn ``std/iter.mm`` → ``iter``, ``std/math/abs.mm`` → ``math-abs``.

    Strips a leading ``std/`` prefix and the ``.mm`` extension, then
    converts path separators to hyphens.  This keeps slugs unique even
    when different sub-directories share the same filename (e.g.
    ``std/abs.mm`` vs ``std/math/abs.mm``).
    """
    p = module_path
    if p.startswith("std/"):
        p = p[len("std/"):]
    # Remove .mm extension
    if p.endswith(".mm"):
        p = p[:-3]
    # Replace path separators and underscores with hyphens, then sanitise
    slug = _SLUG_RE.sub("-", p.replace("/", "-").replace("_", "-").lower()).strip("-")
    return slug or "unknown"


def _module_to_import(module_path: str) -> tuple[str, str]:
    """Return ``(import_path, alias)`` for an ``import`` preamble entry.

    ``std/iter.mm`` → (``"std/iter"``, ``"iter"``).
    Paths outside ``std/`` keep their full stem as the import path.
    """
    path = module_path.strip()
    # Strip a trailing ``.mm`` if present; the mumei ``import`` syntax
    # uses the logical module path (no extension).
    if path.endswith(".mm"):
        path = path[:-3]
    alias = Path(path).name
    alias = _SLUG_RE.sub("_", alias.lower()).strip("_") or "mod"
    return path, alias


def _build_import_preamble(depends_on: list[str]) -> str:
    """Render the ``import ... as ...;`` block for cross-file context."""
    lines: list[str] = []
    seen: set[str] = set()
    for dep in depends_on or []:
        if not isinstance(dep, str) or not dep.strip():
            continue
        import_path, alias = _module_to_import(dep)
        if import_path in seen:
            continue
        seen.add(import_path)
        lines.append(f'import "{import_path}" as {alias};')
    return "\n".join(lines)


def _resolve_max_retries(difficulty: str | None) -> int:
    """Map ``difficulty`` hints into a retry budget."""
    if not isinstance(difficulty, str):
        return _DIFFICULTY_RETRIES["medium"]
    return _DIFFICULTY_RETRIES.get(difficulty.lower(), _DIFFICULTY_RETRIES["medium"])


def _proposal_to_task_id(proposal: dict[str, Any]) -> str:
    """Compose the ``vstd-<slug>`` task id for a proposal."""
    name = proposal.get("name", "")
    slug = _module_to_slug(str(name))
    return f"vstd-{slug}"


def _proposal_filename(proposal: dict[str, Any]) -> str:
    """Compose the ``vstd_<slug>.json`` output filename."""
    name = proposal.get("name", "")
    slug = _module_to_slug(str(name)).replace("-", "_")
    return f"vstd_{slug}.json"


def _module_name_from_path(module_path: str) -> str:
    """Return the module identifier used inside the generated spec."""
    return Path(module_path.rstrip("/")).stem or "module"


def build_spec_from_proposal(
    proposal: dict[str, Any],
    *,
    priority: int | None = None,
) -> dict[str, Any]:
    """Convert one ``analyze_std_gaps`` proposal into a forge task spec.

    The resulting dict matches the schema documented in
    ``forge_tasks/README.md`` (required fields: ``task_id``,
    ``target_file``, ``mode``, ``atoms``).  When the proposal omits
    concrete atoms we emit a single placeholder atom stub so the forge
    pipeline still has enough to dispatch the create-mode generator.

    Parameters
    ----------
    proposal:
        Proposal dict as emitted by ``analyze_std_gaps`` (keys
        ``name`` / ``reason`` / ``depends_on`` / ``difficulty`` /
        optional ``priority`` / optional ``atoms``).
    priority:
        Explicit priority override.  When ``None``, falls back to the
        proposal's own ``priority`` (defaulting to ``100``).
    """
    if not isinstance(proposal, dict):
        raise TypeError("proposal must be a dict")

    name = proposal.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("proposal is missing a 'name' field")

    depends_on_raw = proposal.get("depends_on") or []
    if not isinstance(depends_on_raw, list):
        depends_on_raw = []
    depends_on: list[str] = [d for d in depends_on_raw if isinstance(d, str)]

    import_preamble = _build_import_preamble(depends_on)
    module_name = _module_name_from_path(name)
    reason = proposal.get("reason", "") or ""
    difficulty = proposal.get("difficulty", "medium")

    # Carry through atom stubs when the proposal already hints at concrete
    # atoms; otherwise synthesise a single placeholder so downstream
    # tooling can always unwrap ``atoms[0]``.
    atoms_raw = proposal.get("atoms")
    if isinstance(atoms_raw, list) and atoms_raw:
        atoms: list[dict[str, Any]] = [dict(a) for a in atoms_raw if isinstance(a, dict)]
    else:
        atoms = [
            {
                "name": f"{module_name}_placeholder",
                "description": (
                    reason.strip()
                    or f"Auto-proposed atom for {module_name} from analyze_std_gaps"
                ),
                "inputs": [{"name": "x", "type": "i64"}],
                "return_type": "i64",
                "requires": "true",
                "ensures": "result >= 0 || result < 0",
            }
        ]

    final_priority = priority
    if final_priority is None:
        raw_priority = proposal.get("priority")
        if isinstance(raw_priority, int):
            final_priority = raw_priority
        else:
            final_priority = 100

    spec: dict[str, Any] = {
        "task_id": _proposal_to_task_id(proposal),
        "target_file": name,
        "module_name": module_name,
        "mode": "create",
        "priority": final_priority,
        "description": reason.strip()
        or f"Auto-proposed forge task for {name} (from analyze_std_gaps)",
        "atoms": atoms,
        "max_retries": _resolve_max_retries(str(difficulty)),
        "auto_commit": False,
        "source": "analyze_std_gaps",
        "difficulty": str(difficulty),
    }
    priority_band = proposal.get("priority_band")
    if isinstance(priority_band, str):
        spec["priority_band"] = priority_band
    roadmap_status = proposal.get("roadmap_status")
    if isinstance(roadmap_status, str):
        spec["roadmap_status"] = roadmap_status

    if depends_on:
        spec["depends_on"] = depends_on
        # ``context_files`` is the established way to inject cross-file
        # style context; reuse the same upstream modules the proposal
        # names as dependencies.
        spec["context_files"] = depends_on

    if import_preamble:
        spec["import_preamble"] = import_preamble

    return spec


def build_specs_from_gaps(gaps: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn the full ``analyze_std_gaps`` JSON payload into forge specs."""
    if not isinstance(gaps, dict):
        raise TypeError("gaps payload must be a JSON object")

    proposals = gaps.get("proposals") or []
    if not isinstance(proposals, list):
        raise ValueError("'proposals' must be a list")

    specs: list[dict[str, Any]] = []
    for idx, proposal in enumerate(proposals, start=1):
        if not isinstance(proposal, dict):
            _logger.warning("Skipping non-object proposal at index %d", idx)
            continue
        # When the proposal lacks an explicit priority, fall back to its
        # position in the list so that forge ordering remains stable.
        # Use ``is None`` so an explicit ``priority: 0`` (highest) is
        # preserved instead of being coerced into ``idx`` by ``or``.
        raw_priority = proposal.get("priority")
        spec = build_spec_from_proposal(
            proposal,
            priority=raw_priority if isinstance(raw_priority, int) else idx,
        )
        specs.append(spec)
    return specs


def write_specs(
    specs: list[dict[str, Any]],
    output_dir: Path,
    *,
    overwrite: bool = False,
) -> list[Path]:
    """Serialise each spec to ``<output_dir>/vstd_<slug>.json``.

    Creates *output_dir* if it does not exist.  When ``overwrite`` is
    ``False`` (the default) and a spec file with the same name already
    exists, the new proposal is written alongside with a numeric
    suffix so operators can diff before replacing.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for spec in specs:
        filename = _proposal_filename({"name": spec.get("target_file", "")})
        path = output_dir / filename
        if path.exists() and not overwrite:
            stem = path.stem
            counter = 1
            while True:
                candidate = output_dir / f"{stem}.{counter}.json"
                if not candidate.exists():
                    path = candidate
                    break
                counter += 1
        path.write_text(
            json.dumps(spec, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        written.append(path)
    return written


def _print_summary(specs: list[dict[str, Any]], paths: list[Path]) -> None:
    """Print a human-readable summary of the generated specs."""
    print(f"propose: generated {len(specs)} forge task spec(s)")
    for spec, path in zip(specs, paths):
        deps = spec.get("depends_on") or []
        deps_str = ", ".join(deps) if deps else "(none)"
        print(
            f"  - {spec['task_id']:<30} -> {spec['target_file']} "
            f"[difficulty={spec.get('difficulty', '?')}, "
            f"max_retries={spec.get('max_retries', '?')}, "
            f"depends_on={deps_str}] "
            f"written to {path}"
        )
        reason = spec.get("description", "")
        if reason:
            short = reason.strip().splitlines()[0]
            if len(short) > 100:
                short = short[:97] + "..."
            print(f"      reason: {short}")


def _load_gaps_from_file(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Error: failed to read gaps JSON {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"Error: gaps JSON at {path} must be an object")
    return data
