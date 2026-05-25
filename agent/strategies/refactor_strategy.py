"""Refactoring strategy for meta-architect proposals."""
from __future__ import annotations

import re
from typing import Any

from agent.strategies.retry_history import RetryHistory


def should_trigger_meta_architect(history: RetryHistory) -> bool:
    """Determine if the meta-architect should be triggered."""
    if history.is_same_error_repeating():
        return True
    if len(history.attempts) >= 5:
        return True
    return False


def apply_refactoring_proposal(
    proposal: dict[str, Any],
    source_code: str,
) -> str:
    """Apply a refactoring proposal to source code."""
    refactoring_type = proposal.get("refactoring_type")
    changes = proposal.get("changes", {})

    if refactoring_type == "relax_requires":
        return _apply_relax_requires(source_code, changes)
    if refactoring_type == "strengthen_ensures":
        return _apply_strengthen_ensures(source_code, changes)
    if refactoring_type == "split_atom":
        return _apply_split_atom(source_code, changes)
    return source_code


def _apply_relax_requires(source_code: str, changes: dict[str, Any]) -> str:
    new_requires = str(changes.get("requires", "true")).strip() or "true"
    return _replace_contract_clause(
        source_code,
        atom_name=_optional_atom_name(changes),
        clause="requires",
        value=new_requires,
    )


def _apply_strengthen_ensures(source_code: str, changes: dict[str, Any]) -> str:
    new_ensures = str(changes.get("ensures", "true")).strip() or "true"
    return _replace_contract_clause(
        source_code,
        atom_name=_optional_atom_name(changes),
        clause="ensures",
        value=new_ensures,
    )


def _apply_split_atom(source_code: str, changes: dict[str, Any]) -> str:
    return source_code


def _optional_atom_name(changes: dict[str, Any]) -> str | None:
    atom = changes.get("atom")
    if isinstance(atom, str) and atom.strip():
        return atom.strip()
    return None


def _replace_contract_clause(
    source_code: str,
    *,
    atom_name: str | None,
    clause: str,
    value: str,
) -> str:
    block_bounds = _atom_block_bounds(source_code, atom_name)
    if block_bounds is None:
        return source_code

    start, end = block_bounds
    block = source_code[start:end]
    pattern = re.compile(
        rf"(?P<indent>^[ \t]*){clause}(?P<colon>\s*:)?(?P<body>.*?);",
        flags=re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(block)
    if match is None:
        return source_code

    indent = match.group("indent")
    colon = match.group("colon") or ""
    replacement = f"{indent}{clause}{colon} {value};"
    updated_block = block[:match.start()] + replacement + block[match.end():]
    return source_code[:start] + updated_block + source_code[end:]


def _atom_block_bounds(source_code: str, atom_name: str | None) -> tuple[int, int] | None:
    matches = list(re.finditer(r"\batom\s+([A-Za-z_][A-Za-z0-9_:]*)", source_code))
    if not matches:
        return None
    for index, match in enumerate(matches):
        name = match.group(1)
        if atom_name is not None and name != atom_name:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(source_code)
        return match.start(), end
    return None
