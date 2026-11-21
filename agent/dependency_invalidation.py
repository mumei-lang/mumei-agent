"""Dependency-aware invalidation map over the std ``.mm`` import graph.

The descriptor derives transitive dependents from compiler-mirrored import
resolution and the implicit prelude dependency. It is detection-only
metadata: no check is re-run, no contract diff is produced, and no
persistent cache or evidence acceptance is implied.
"""

from __future__ import annotations

import posixpath
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from agent.gap_rules import _IMPORT_RE

SCHEMA_VERSION = "mumei.std-dependency-invalidation/v1"
IMPLICIT_IMPORTS = ("std/prelude.mm",)

CHECKS_NOT_PERFORMED = [
    "re_verification",
    "contract_level_diff",
    "symbol_resolution",
    "cycle_analysis",
    "external_std_path_resolution",
]


def _declared_import_targets(text: str) -> list[str]:
    """Return raw ``import "..."`` targets in declaration order."""
    targets: list[str] = []
    for line in text.splitlines():
        match = _IMPORT_RE.match(line)
        if match:
            targets.append(match.group(1).strip())
    return targets


def _resolve_import_target(
    target: str, importer: str, file_keys: set[str]
) -> str | None:
    path = target if target.endswith(".mm") else target + ".mm"
    if PurePosixPath(path).is_absolute() or PureWindowsPath(path).is_absolute():
        return None

    importer_relative = posixpath.normpath(
        posixpath.join(posixpath.dirname(importer), path)
    )
    if importer_relative in file_keys:
        return importer_relative

    std_target = target
    while std_target.startswith("./"):
        std_target = std_target[2:]
    if std_target.startswith("std/"):
        std_path = std_target if std_target.endswith(".mm") else std_target + ".mm"
        std_fallback = posixpath.normpath(std_path)
        if std_fallback in file_keys:
            return std_fallback
    return None


def _build_import_graph(
    std_dir: Path,
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Build resolved import edges and unresolved targets for ``std_dir``."""
    files = {
        mm_file.relative_to(std_dir.parent).as_posix(): mm_file
        for mm_file in sorted(std_dir.rglob("*.mm"))
    }
    file_keys = set(files)
    graph: dict[str, list[str]] = {}
    unresolved: dict[str, list[str]] = {}

    for key, mm_file in files.items():
        try:
            text = mm_file.read_text(encoding="utf-8")
        except OSError:
            graph[key] = []
            unresolved[key] = ["<unreadable>"]
            continue

        dependencies: set[str] = set()
        missing: list[str] = []
        for target in _declared_import_targets(text):
            dependency = _resolve_import_target(target, key, file_keys)
            if dependency is None:
                missing.append(target)
            elif dependency != key:
                dependencies.add(dependency)
        if missing:
            unresolved[key] = missing
        graph[key] = sorted(dependencies)

    prelude = IMPLICIT_IMPORTS[0]
    if prelude in graph:
        for key, deps in graph.items():
            if key != prelude and prelude not in deps:
                graph[key] = sorted([*deps, prelude])

    return graph, unresolved


def dependency_invalidation_map(std_dir: Path, changed: str) -> dict[str, Any]:
    """Map files to re-derive, undetermined, or unaffected by *changed*.

    ``re_derive`` contains files transitively depending on *changed*.
    ``undetermined`` contains files whose own unresolved imports, or those
    of their dependencies, prevent a sound unaffected classification.
    ``unaffected`` contains files with neither a resolved path to *changed*
    nor unresolved imports in their dependency closure.

    The descriptor keeps unresolved declared targets in
    ``unresolved_imports`` and identifies implicit prelude imports in
    ``implicit_imports``. It makes no claims about external std-path
    resolution outside the scanned directory.
    """
    graph, unresolved = _build_import_graph(std_dir)

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

    undetermined: set[str] = set(unresolved)
    frontier = list(undetermined)
    while frontier:
        node = frontier.pop()
        for dependent in dependents.get(node, ()):
            if dependent not in undetermined:
                undetermined.add(dependent)
                frontier.append(dependent)

    files = set(graph)
    undetermined.difference_update(re_derive)
    undetermined.discard(changed)
    unaffected = files - re_derive - undetermined - {changed}

    return {
        "schema_version": SCHEMA_VERSION,
        "changed": changed,
        "re_derive": sorted(re_derive),
        "undetermined": sorted(undetermined),
        "unaffected": sorted(unaffected),
        "unresolved_imports": unresolved,
        "implicit_imports": [name for name in IMPLICIT_IMPORTS if name in graph],
        "checks_not_performed": list(CHECKS_NOT_PERFORMED),
    }
