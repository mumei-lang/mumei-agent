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

from agent.core_evidence import UNPERFORMED_CHECK_RECOVERY_SCHEMA

SCHEMA_VERSION = "mumei.std-dependency-invalidation/v1"
DEPENDENCY_CHECKS_SCHEMA = "mumei.std-dependency-checks/v1"
IMPLICIT_IMPORTS = ("std/prelude.mm",)

CHECKS_NOT_PERFORMED = [
    "re_verification",
    "contract_level_diff",
    "symbol_resolution",
    "cycle_analysis",
    "external_std_path_resolution",
]


def _scan_import_declarations(text: str) -> tuple[list[str], int]:
    """Return import string targets and malformed import declaration count."""
    tokens: list[tuple[str, str]] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char.isspace():
            index += 1
            continue
        if text.startswith("//", index):
            newline = text.find("\n", index)
            index = len(text) if newline == -1 else newline + 1
            continue
        if char == '"':
            index += 1
            value: list[str] = []
            while index < len(text):
                char = text[index]
                index += 1
                if char == '"':
                    break
                if char == "\\":
                    if index == len(text):
                        value.append("\\")
                        break
                    escaped = text[index]
                    index += 1
                    escapes = {"n": "\n", "t": "\t", "\\": "\\", '"': '"'}
                    value.append(escapes.get(escaped, "\\" + escaped))
                else:
                    value.append(char)
            tokens.append(("string", "".join(value)))
            continue
        if char.isascii() and (char.isalpha() or char == "_"):
            end = index + 1
            while end < len(text):
                next_char = text[end]
                if not (
                    next_char.isascii() and (next_char.isalnum() or next_char == "_")
                ):
                    break
                end += 1
            tokens.append(("identifier", text[index:end]))
            index = end
            continue
        tokens.append(("punct", char))
        index += 1

    targets: list[str] = []
    malformed_count = 0
    for token_index, (kind, value) in enumerate(tokens):
        if kind == "identifier" and value == "import":
            next_token = tokens[token_index + 1 : token_index + 2]
            if next_token and next_token[0][0] == "string":
                targets.append(next_token[0][1])
            else:
                malformed_count += 1
    return targets, malformed_count


def _declared_import_targets(text: str) -> list[str]:
    """Return import string targets in declaration order."""
    return _scan_import_declarations(text)[0]


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
        targets, malformed_count = _scan_import_declarations(text)
        for target in targets:
            dependency = _resolve_import_target(target, key, file_keys)
            if dependency is None:
                missing.append(target)
            elif dependency != key:
                dependencies.add(dependency)
        if malformed_count:
            missing.append("<malformed import>")
        if missing:
            unresolved[key] = missing
        graph[key] = sorted(dependencies)

    prelude = IMPLICIT_IMPORTS[0]
    if prelude in graph:
        for key, deps in graph.items():
            if key != prelude and prelude not in deps:
                graph[key] = sorted([*deps, prelude])

    return graph, unresolved


def _real_path_aliases(
    std_dir: Path, file_keys: set[str]
) -> tuple[dict[Path, set[str]], dict[str, set[str]]]:
    aliases_by_path: dict[Path, set[str]] = {}
    for key in file_keys:
        path = std_dir.parent / key
        try:
            real_path = path.resolve()
        except OSError:
            real_path = path
        aliases_by_path.setdefault(real_path, set()).add(key)
    aliases_by_key = {
        key: aliases for aliases in aliases_by_path.values() for key in aliases
    }
    return aliases_by_path, aliases_by_key


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
    aliases_by_path, aliases_by_key = _real_path_aliases(std_dir, set(graph))
    changed_path = std_dir.parent / changed
    try:
        changed_real_path = changed_path.resolve()
    except OSError:
        changed_real_path = changed_path
    changed_aliases = aliases_by_path.get(changed_real_path, set())

    dependents: dict[str, set[str]] = {}
    for rel, deps in graph.items():
        for dep in deps:
            dependents.setdefault(dep, set()).add(rel)

    seeds = {changed, *changed_aliases}
    re_derive = changed_aliases - {changed}
    frontier = [dependent for seed in seeds for dependent in dependents.get(seed, ())]
    visited: set[str] = set()
    while frontier:
        node = frontier.pop()
        if node in visited:
            continue
        visited.add(node)
        aliases = aliases_by_key.get(node, {node})
        re_derive.update(aliases)
        for alias in aliases:
            frontier.extend(dependents.get(alias, ()))

    undetermined: set[str] = set(unresolved)
    frontier = list(undetermined)
    visited.clear()
    while frontier:
        node = frontier.pop()
        if node in visited:
            continue
        visited.add(node)
        aliases = aliases_by_key.get(node, {node})
        undetermined.update(aliases)
        for alias in aliases:
            frontier.extend(dependents.get(alias, ()))

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


def inherit_dependency_checks(std_dir: Path, reports: dict[str, Any]) -> dict[str, Any]:
    """Carry outstanding dependency checks into schema-open file records.

    Each entry in ``files`` is accepted directly by
    ``evaluate_unperformed_check_recovery``.
    """
    if type(reports) is not dict:
        raise ValueError("reports must be an object")

    outstanding_by_file: dict[str, list[str]] = {}
    for key, report in reports.items():
        if type(key) is not str:
            raise ValueError("report keys must be strings")
        if type(report) is not dict:
            raise ValueError("reports must contain objects")
        if report.get("schema_version") == UNPERFORMED_CHECK_RECOVERY_SCHEMA:
            outstanding = report.get("unrecovered")
            if type(outstanding) is not list:
                raise ValueError("recovery reports must contain an unrecovered list")
        else:
            outstanding = report.get("checks_not_performed", [])
            if type(outstanding) is not list:
                outstanding = []
        outstanding_by_file[key] = [
            check for check in outstanding if type(check) is str
        ]

    graph, unresolved = _build_import_graph(std_dir)
    _, aliases_by_key = _real_path_aliases(std_dir, set(graph))

    def dependency_closure(file_key: str) -> set[str]:
        closure: set[str] = set()
        visited: set[str] = set()
        frontier = list(graph[file_key])
        while frontier:
            node = frontier.pop()
            if node in visited:
                continue
            aliases = aliases_by_key.get(node, {node})
            for alias in aliases:
                if alias in visited:
                    continue
                visited.add(alias)
                if alias != file_key:
                    closure.add(alias)
                frontier.extend(graph.get(alias, []))
        closure.discard(file_key)
        return closure

    files: dict[str, dict[str, Any]] = {}
    for file_key in sorted(graph):
        closure = dependency_closure(file_key)
        inherited_sources: dict[str, list[str]] = {}
        for dependency in closure:
            for check in outstanding_by_file.get(dependency, []):
                inherited_sources.setdefault(check, []).append(dependency)
        inherited = {
            check: sorted(set(dependencies))
            for check, dependencies in sorted(inherited_sources.items())
        }
        dependencies_without_report = sorted(
            dependency for dependency in closure if dependency not in reports
        )
        unresolved_in_closure = file_key in unresolved or any(
            dependency in unresolved for dependency in closure
        )
        markers: set[str] = set()
        if dependencies_without_report:
            markers.add("dependency_verification")
        if unresolved_in_closure:
            markers.add("dependency_resolution")
        own = outstanding_by_file.get(file_key, [])
        checks_not_performed = sorted(set(own) | set(inherited) | markers)
        files[file_key] = {
            "own": own,
            "inherited": inherited,
            "dependencies_without_report": dependencies_without_report,
            "unresolved_in_closure": unresolved_in_closure,
            "checks_not_performed": checks_not_performed,
        }

    return {
        "schema_version": DEPENDENCY_CHECKS_SCHEMA,
        "files": files,
        "unknown_reports": sorted(set(reports) - set(graph)),
        "checks_not_performed": [
            "re_verification",
            "evidence_binding",
            "symbol_resolution",
            "external_std_path_resolution",
        ],
    }
