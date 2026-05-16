"""Prompt builder for high-density Mumei property generation."""
from __future__ import annotations

from typing import Mapping


def build_dense_property_prompt(
    spec: Mapping[str, object],
    current_properties: Mapping[str, list[str]],
) -> str:
    """Build the prompt used to synthesize compact contracts."""
    return f"""# Generate High-Density Mumei Properties

## Specification
{dict(spec)}

## Current Properties
Requires: {current_properties.get("requires", [])}
Ensures: {current_properties.get("ensures", [])}

## Objective
Generate dense requires/ensures clauses that preserve the intended contract while
reducing Z3 verification cost.

## Z3 Efficiency Rules
1. Prefer quantifier-free linear arithmetic and direct equalities.
2. Combine related bounds into one conjunction and remove redundant predicates.
3. Put cheap guard predicates first: non-null/non-empty, ranges, divisors, equalities.
4. Avoid disjunctions, implications, quantifiers, non-linear arithmetic, and
   repeated function calls unless required by the spec.
5. Reuse existing variable names, result, effects, and Mumei type refinements exactly.
6. Do not weaken safety: keep every semantic precondition/postcondition required by the spec.

## Output
Return only this Mumei contract block, with no prose:
```mumei
requires: <dense requires clause>;
ensures: <dense ensures clause>;
```
"""
