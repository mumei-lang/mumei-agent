"""Dependency-aware invalidation map over the std ``.mm`` import graph.

Deeper cross-file layer on top of the existing blast-radius surface
(:func:`agent.proliferate_healing.check_blast_radius`): the blast radius
re-verifies every existing ``std/*.mm`` file and reports which broke.
This module answers the next question — *which files could a change have
invalidated at all?* — by deriving the transitive dependents of a
changed file from the same ``import "..."`` graph used by
``analyze_gaps``.

The produced descriptor is pure metadata in the established style of the
C07 dependent-invalidation walk: **detection, not recomputation**. The
host decides what to rebuild or re-verify; no check is re-run here, no
contract diff is produced, no symbol resolution is attempted, and no
persistent cache or evidence acceptance is implied.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.gap_rules import _IMPORT_RE, _scan_std_imports

SCHEMA_VERSION = "mumei.std-dependency-invalidation/v1"

# Honest limits of the descriptor: it maps import-declared dependents.
CHECKS_NOT_PERFORMED = [
    "re_verification",
    "contract_level_diff",
    "symbol_resolution",
    "cycle_analysis",
    "transitive_prelude_import",
]


def _declared_import_targets(text: str) -> list[str]:
    """Raw ``import "..."`` targets declared in *text* (order preserved).

    Commented usage lines (``//   import ...``) never match because the
    anchor requires ``import`` at the start of the (whitespace-stripped)
    line — the same convention ``_scan_std_imports`` relies on.
    """
    targets: list[str] = []
    for line in text.splitlines():
        match = _IMPORT_RE.match(line)
        if match:
            targets.append(match.group(1).strip())
    return targets


def dependency_invalidation_map(std_dir: Path, changed: str) -> dict[str, Any]:
    """Map the files transitively invalidated by *changed*.

    Parameters
    ----------
    std_dir:
        The ``std/`` directory scanned by ``_scan_std_imports``.
    changed:
        The changed ``.mm`` file as a repo-relative path in the
        ``std/...`` keyspace produced by the scan (for example
        ``"std/math/safe_mul.mm"``). A file outside the graph (for
        example a brand-new module nothing imports yet) simply yields an
        empty ``re_derive`` set.

    Returns a ``mumei.std-dependency-invalidation/v1`` descriptor:

    - ``re_derive`` — every existing file that transitively imports
      *changed*. These are the files whose checks a host should
      re-derive rather than assume unaffected; a cycle lands all its
      members here whenever any of them is reachable.
    - ``unaffected`` — files whose complete resolved import set contains
      no path to *changed*. Correct because unresolved import names
      cannot resolve to *changed* (if they did, they would resolve —
      the scan sees the file on disk).
    - ``unresolved_imports`` — per file, declared targets that resolved
      to nothing under ``std_dir``. Informational: they can never name
      an existing *changed* file, so they do not weaken ``unaffected``.
    - ``checks_not_performed`` — the checks this descriptor explicitly
      does not run.
    """
    graph = _scan_std_imports(std_dir)

    dependents: dict[str, set[str]] = {}
    for rel, deps in graph.items():
        for dep in deps:
            dependents.setdefault(dep, set()).add(rel)

    re_derive: set[str] = set()
    frontier = list(dependents.get(changed, ()))
    while frontier:
        node = frontier.pop()
        if node in re_derive:
            continue
        re_derive.add(node)
        frontier.extend(dependents.get(node, ()))

    files = set(graph)
    files.discard(changed)
    unaffected = sorted(files - re_derive)

    unresolved: dict[str, list[str]] = {}
    for mm_file in sorted(std_dir.rglob("*.mm")):
        rel = str(mm_file.relative_to(std_dir.parent)).replace("\\", "/")
        try:
            text = mm_file.read_text(encoding="utf-8")
        except OSError:
            continue
        resolved = {t[: -len(".mm")] for t in graph.get(rel, [])}
        missing = [
            target
            for target in _declared_import_targets(text)
            if target not in resolved and target + ".mm" != rel
        ]
        if missing:
            unresolved[rel] = missing

    return {
        "schema_version": SCHEMA_VERSION,
        "changed": changed,
        "re_derive": sorted(re_derive),
        "unaffected": unaffected,
        "unresolved_imports": unresolved,
        "checks_not_performed": list(CHECKS_NOT_PERFORMED),
    }
