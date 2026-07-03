"""Helper utilities for specification refinement (P6-C).

These functions perform contract-manifest loading and contract-integrity
checking used by :func:`agent.strategies.spec_refinement.refine_spec`.
They contain no LLM interaction and are pure with respect to their inputs.
"""
from __future__ import annotations

import json
from collections.abc import Mapping


def _load_contract_manifest(path: str | None) -> dict | None:
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as file:
            loaded = json.load(file)
    except OSError as exc:
        raise ValueError(f"Failed to load contract manifest '{path}': {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid contract manifest JSON '{path}': {exc}") from exc
    if not isinstance(loaded, dict):
        raise ValueError(f"Contract manifest '{path}' is not a JSON object")
    return loaded


def check_contract_integrity(
    original_spec: dict,
    refined_spec: dict,
    manifest: dict | None = None,
) -> tuple[bool, str]:
    """Check if the contract (specification) has been mutated."""
    if manifest is None:
        return True, ""

    protected_fields = (
        "requires",
        "ensures",
        "effects",
        "invariant",
        "effect_pre",
        "effect_post",
        "contracts",
        "fn_contracts",
    )

    for field in protected_fields:
        original_val = original_spec.get(field)
        refined_val = refined_spec.get(field)

        if original_val != refined_val:
            return False, (
                f"Contract mutation detected: field '{field}' changed from "
                f"'{original_val}' to '{refined_val}'. "
                "Specification changes are not allowed. "
                "Please modify only the implementation (body)."
            )

    original_atoms = original_spec.get("atoms", [])
    refined_atoms = refined_spec.get("atoms", [])

    if len(original_atoms) != len(refined_atoms):
        return False, "Contract mutation detected: number of atoms changed"

    for orig_atom, ref_atom in zip(original_atoms, refined_atoms, strict=False):
        if not isinstance(orig_atom, Mapping) or not isinstance(ref_atom, Mapping):
            return False, "Contract mutation detected: atom entry shape changed"
        atom_name = orig_atom.get("name")
        if atom_name != ref_atom.get("name"):
            return False, (
                f"Contract mutation detected: atom '{atom_name}' was renamed "
                f"to '{ref_atom.get('name')}'"
            )
        for field in protected_fields:
            if orig_atom.get(field) != ref_atom.get(field):
                return False, (
                    f"Contract mutation detected in atom '{atom_name}': "
                    f"field '{field}' changed. Specification changes are not allowed."
                )

    return True, ""
