"""Offline std/ gap-analysis rules and helpers.

This module is the **fallback** copy of the gap-rule logic that the
mumei MCP server's :func:`mcp_server.analyze_std_gaps` exposes.  When
the mumei repo is reachable via ``PYTHONPATH`` (CI / side-by-side
checkouts), :mod:`agent.proliferate` prefers calling the MCP-side tool
directly via :func:`agent.propose._load_gaps_from_mcp` so the rule set
stays in lockstep with the compiler repository.

The contents below were extracted from ``agent/proliferate.py`` so the
"local-only" path is clearly isolated and can be edited or refreshed
independently from the rest of the proliferation pipeline.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# Regex patterns ported from mumei's mcp_server.py helper functions.
_IMPORT_RE = re.compile(r'^\s*import\s+"([^"]+)"\s*(?:as\s+\w+\s*)?;')
_TRUSTED_ATOM_RE = re.compile(r"^\s*trusted\s+atom\s+(\w+)")
_TODO_MARKER_RE = re.compile(
    r"//.*?\b(TODO|FIXME|XXX|HACK|Phase\s+[A-Z0-9]+)\b[^\n]*",
    re.IGNORECASE,
)

# Hard-coded gap rules (mirror of ``mcp_server._STD_GAP_RULES`` in the
# mumei repo).  Update both copies in lockstep, or set
# ``PREFER_MCP_GAPS=true`` on the CI runner so this list is bypassed
# entirely in favor of the authoritative rules from the mumei checkout.
_STD_GAP_RULES: list[dict[str, Any]] = [
    {
        "target": "std/iter.mm",
        "reason": (
            "Collection traversal common interface. "
            "std/list.mm / std/alloc.mm containers lack iterators."
        ),
        "depends_on": ["std/prelude.mm"],
        "difficulty": "medium",
        "trigger": {
            "has_container_without_iter": [
                "std/container",
                "std/list.mm",
                "std/alloc.mm",
            ],
            "missing": "std/iter.mm",
        },
    },
    {
        "target": "std/core.mm",
        "reason": (
            "Type conversion safety proofs are scattered. "
            "Consolidate Size/Index/NonZero axioms and checked_add/sub/mul."
        ),
        "depends_on": ["std/prelude.mm"],
        "difficulty": "low",
        "trigger": {"missing": "std/core.mm"},
    },
    {
        "target": "std/trait/iterable.mm",
        "reason": (
            "Common interface for Vector/List/BoundedArray. "
            "Connect Sequential trait with iterator."
        ),
        "depends_on": ["std/prelude.mm", "std/alloc.mm"],
        "difficulty": "medium",
        "trigger": {
            "missing": "std/trait/iterable.mm",
            "requires_present": ["std/alloc.mm"],
        },
    },
    {
        "target": "std/hash.mm",
        "reason": (
            "prelude.mm has Eq/Ord but Hash law is incomplete. "
            "Provide Hashable trait implementation and collision resistance law."
        ),
        "depends_on": ["std/prelude.mm"],
        "difficulty": "medium",
        "trigger": {"missing": "std/hash.mm"},
    },
    # std/math 系（Z3 整数理論ネイティブ）
    {
        "target": "std/math/abs.mm",
        "reason": (
            "Absolute value with i64::MIN overflow handling. "
            "Z3 integer theory can fully verify the edge case."
        ),
        "depends_on": ["std/core.mm"],
        "difficulty": "low",
        "trigger": {"missing": "std/math/abs.mm"},
    },
    {
        "target": "std/math/safe_div.mm",
        "reason": (
            "Division with compile-time zero-divisor elimination "
            "using NonZero type from core.mm."
        ),
        "depends_on": ["std/core.mm"],
        "difficulty": "low",
        "trigger": {"missing": "std/math/safe_div.mm"},
    },
    {
        "target": "std/math/safe_mul.mm",
        "reason": (
            "Multiplication with full overflow prevention proof. "
            "Extends checked_mul from core.mm with richer contracts."
        ),
        "depends_on": ["std/core.mm"],
        "difficulty": "low",
        "trigger": {"missing": "std/math/safe_mul.mm"},
    },
    {
        "target": "std/math/pow.mm",
        "reason": (
            "Integer exponentiation with overflow bounds proof. "
            "Z3 can verify base cases and inductive overflow limits."
        ),
        "depends_on": ["std/core.mm", "std/math/safe_mul.mm"],
        "difficulty": "medium",
        "trigger": {
            "missing": "std/math/pow.mm",
            "requires_present": ["std/core.mm"],
        },
    },
    {
        "target": "std/math/factorial.mm",
        "reason": (
            "Factorial calculation with n >= 0 precondition and "
            "result >= 1 postcondition. Z3 integer theory can verify it."
        ),
        "depends_on": ["std/core.mm"],
        "difficulty": "medium",
        "trigger": {
            "missing": "std/math/factorial.mm",
            "requires_present": ["std/core.mm"],
        },
    },
    {
        "target": "std/math/fibonacci.mm",
        "reason": (
            "Fibonacci sequence with loop invariant and decreases "
            "termination proof."
        ),
        "depends_on": ["std/core.mm"],
        "difficulty": "medium",
        "trigger": {
            "missing": "std/math/fibonacci.mm",
            "requires_present": ["std/core.mm"],
        },
    },
    # std/container 系（Z3 配列理論）
    {
        "target": "std/container/ring_buffer.mm",
        "reason": (
            "Fixed-size ring buffer with head/tail pointer wraparound "
            "safety proof. Z3 modular arithmetic."
        ),
        "depends_on": ["std/core.mm"],
        "difficulty": "medium",
        "trigger": {"missing": "std/container/ring_buffer.mm"},
    },
    {
        "target": "std/container/binary_heap.mm",
        "reason": (
            "Binary heap with heap property maintenance proof after "
            "insert/delete. Z3 array + integer theory."
        ),
        "depends_on": ["std/core.mm", "std/container/bounded_array.mm"],
        "difficulty": "high",
        "trigger": {
            "missing": "std/container/binary_heap.mm",
            "requires_present": ["std/container/bounded_array.mm"],
        },
    },
    {
        "target": "std/container/sorted_map.mm",
        "reason": (
            "Sorted key-value map with sort invariant preservation "
            "after insert. Z3 can verify the array ordering invariant."
        ),
        "depends_on": ["std/container/bounded_array.mm"],
        "difficulty": "high",
        "trigger": {
            "missing": "std/container/sorted_map.mm",
            "requires_present": ["std/container/bounded_array.mm"],
        },
    },
    {
        "target": "std/string/validator.mm",
        "reason": (
            "String validation helpers such as is_numeric and "
            "is_alphanumeric for RegTech demo scenarios."
        ),
        "depends_on": ["std/core.mm"],
        "difficulty": "low",
        "trigger": {"missing": "std/string/validator.mm"},
    },
    {
        "target": "std/math/extended.mm",
        "reason": (
            "Extended arithmetic helpers such as signum, bounded square, "
            "floor mean, and absolute distance."
        ),
        "depends_on": [
            "std/core.mm",
            "std/math/abs.mm",
            "std/math/safe_div.mm",
            "std/math/safe_mul.mm",
        ],
        "difficulty": "medium",
        "trigger": {
            "missing": "std/math/extended.mm",
            "requires_present": [
                "std/core.mm",
                "std/math/abs.mm",
                "std/math/safe_div.mm",
                "std/math/safe_mul.mm",
            ],
        },
    },
    {
        "target": "std/core_ranges.mm",
        "reason": (
            "Interval/range predicates such as disjoint/overlap witnesses, "
            "non-negative width, and point-before-range for container bounds "
            "and scheduling logic. Linear integer contracts fully inside the "
            "Z3 decidable fragment."
        ),
        "depends_on": ["std/core.mm"],
        "difficulty": "low",
        "trigger": {
            "missing": "std/core_ranges.mm",
            "requires_present": ["std/core.mm"],
        },
    },
    {
        "target": "std/crypto/primitives.mm",
        "reason": (
            "Structural crypto primitive validators for key, nonce, digest, "
            "and equality-witness safety contracts."
        ),
        "depends_on": [
            "std/core.mm",
            "std/crypto/hash.mm",
            "std/string_utils.mm",
        ],
        "difficulty": "medium",
        "trigger": {
            "missing": "std/crypto/primitives.mm",
            "requires_present": [
                "std/core.mm",
                "std/crypto/hash.mm",
                "std/string_utils.mm",
            ],
        },
    },
]


def _scan_std_imports(std_dir: Path) -> dict[str, list[str]]:
    """Build a dependency graph of .mm files under *std_dir*.

    Returns a dict mapping ``std/X.mm`` relative paths to their sorted
    list of import targets.
    """
    if not std_dir.exists():
        return {}

    available: dict[str, str] = {}
    for mm_file in std_dir.rglob("*.mm"):
        rel = str(mm_file.relative_to(std_dir.parent)).replace("\\", "/")
        import_path = rel[: -len(".mm")]
        available[import_path] = rel

    dependency_graph: dict[str, list[str]] = {}
    for mm_file in sorted(std_dir.rglob("*.mm")):
        rel = str(mm_file.relative_to(std_dir.parent)).replace("\\", "/")
        try:
            text = mm_file.read_text(encoding="utf-8")
        except OSError:
            dependency_graph[rel] = []
            continue
        deps: list[str] = []
        for line in text.splitlines():
            m = _IMPORT_RE.match(line)
            if not m:
                continue
            target = m.group(1).strip()
            resolved = available.get(target)
            if resolved and resolved != rel and resolved not in deps:
                deps.append(resolved)
        dependency_graph[rel] = sorted(deps)
    return dependency_graph


def _collect_trusted_atoms(std_dir: Path) -> list[dict[str, Any]]:
    """Return list of trusted atom entries found in *std_dir*."""
    results: list[dict[str, Any]] = []
    for mm_file in sorted(std_dir.rglob("*.mm")):
        rel = str(mm_file.relative_to(std_dir.parent)).replace("\\", "/")
        try:
            lines = mm_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for idx, line in enumerate(lines):
            m = _TRUSTED_ATOM_RE.match(line)
            if not m:
                continue
            atom_name = m.group(1)
            reason = ""
            look = idx - 1
            if look >= 0 and lines[look].strip().startswith("//"):
                reason = lines[look].strip().lstrip("/ ").strip()
            if not reason:
                end = min(idx + 10, len(lines))
                body_text = " ".join(line.strip() for line in lines[idx + 1 : end])
                if re.search(r"body\s*:\s*\{\s*\}", body_text):
                    reason = "body is stub"
                else:
                    reason = "trusted (proof hole)"
            results.append(
                {"file": rel, "atom": atom_name, "line": idx + 1, "reason": reason}
            )
    return results


def _collect_todo_comments(std_dir: Path) -> list[dict[str, Any]]:
    """Return list of TODO/FIXME/XXX/HACK comments in *std_dir*."""
    results: list[dict[str, Any]] = []
    for mm_file in sorted(std_dir.rglob("*.mm")):
        rel = str(mm_file.relative_to(std_dir.parent)).replace("\\", "/")
        try:
            lines = mm_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for idx, line in enumerate(lines):
            m = _TODO_MARKER_RE.search(line)
            if not m:
                continue
            results.append(
                {
                    "file": rel,
                    "line": idx + 1,
                    "text": line.strip().lstrip("/ ").strip(),
                }
            )
    return results


def _evaluate_rule(
    rule: dict[str, Any],
    existing_paths: set[str],
    std_dir: Path,
) -> bool:
    """Return True if the rule's trigger conditions apply."""
    trigger = rule.get("trigger", {})
    missing = trigger.get("missing")
    if missing and missing in existing_paths:
        return False
    for required in trigger.get("requires_present", []):
        if required not in existing_paths:
            return False
    container_check = trigger.get("has_container_without_iter")
    if container_check:
        has_container = any(
            (std_dir.parent / path).exists()
            or (path.endswith("/") and (std_dir.parent / path.rstrip("/")).exists())
            for path in container_check
        )
        if not has_container:
            return False
    return True


def analyze_gaps_local(std_dir: Path) -> dict[str, Any]:
    """Pure-filesystem analog of mumei's ``analyze_std_gaps`` MCP tool.

    See :func:`agent.proliferate.analyze_gaps` for the wrapper that
    optionally delegates to the MCP server when ``PREFER_MCP_GAPS`` is
    enabled.
    """
    if not std_dir.exists():
        return {
            "dependency_graph": {},
            "trusted_atoms": [],
            "todo_comments": [],
            "proposals": [],
        }

    dependency_graph = _scan_std_imports(std_dir)
    trusted_atoms = _collect_trusted_atoms(std_dir)
    todo_comments = _collect_todo_comments(std_dir)

    existing_paths = set(dependency_graph.keys())

    proposals: list[dict[str, Any]] = []
    for rule in _STD_GAP_RULES:
        if not _evaluate_rule(rule, existing_paths, std_dir):
            continue
        proposals.append(
            {
                "name": rule["target"],
                "reason": rule["reason"],
                "depends_on": rule["depends_on"],
                "difficulty": rule["difficulty"],
            }
        )

    # Rank proposals: lower difficulty and fewer unmet deps rank higher.
    difficulty_weight = {"low": 0, "medium": 1, "high": 2}

    def _rank_key(p: dict[str, Any]) -> tuple[int, int]:
        diff = difficulty_weight.get(p["difficulty"], 3)
        unmet = sum(1 for dep in p["depends_on"] if dep not in existing_paths)
        return (diff, unmet)

    proposals.sort(key=_rank_key)
    for i, p in enumerate(proposals[:3], start=1):
        p["priority"] = i
    proposals = proposals[:3]

    return {
        "dependency_graph": dependency_graph,
        "trusted_atoms": trusted_atoms,
        "todo_comments": todo_comments,
        "proposals": proposals,
    }


__all__ = [
    "_IMPORT_RE",
    "_TRUSTED_ATOM_RE",
    "_TODO_MARKER_RE",
    "_STD_GAP_RULES",
    "_scan_std_imports",
    "_collect_trusted_atoms",
    "_collect_todo_comments",
    "_evaluate_rule",
    "analyze_gaps_local",
]
