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

## Contract Compression Algorithm
1. Split each clause into top-level conjunctions.
2. Remove duplicate predicates and predicates already implied by a stronger bound.
3. Prefer the cheapest equivalent predicate shape:
   arithmetic comparison > equality > logical conjunction > function call >
   disjunction/implication > quantifier.
4. Keep the final contract semantically equivalent or stronger, never weaker.

## Z3 Efficiency Rules
1. Prefer quantifier-free linear arithmetic and direct equalities.
2. Encode ranges with the strongest lower/upper bounds only.
3. Put cheap guard predicates first: non-null/non-empty, ranges, divisors, equalities.
4. Avoid disjunctions, implications, quantifiers, non-linear arithmetic, and
   repeated function calls unless required by the spec.
5. Reuse existing variable names, result, effects, and Mumei type refinements exactly.
6. Do not weaken safety: keep every semantic precondition/postcondition required by the spec.

## Proof-Friendly Guidance
- Use solver-stable linear integer arithmetic whenever possible.
- Make postconditions directly mention `result` instead of hiding it behind helper calls.
- Use bounded quantifiers only when no finite arithmetic summary preserves the intent.
- Avoid chains of implications; rewrite them as explicit guards in `requires` and
  direct facts in `ensures` when equivalent.
- Keep predicates independent so Z3 can discharge them compositionally.

## Output
Return only this Mumei contract block, with no prose:
```mumei
requires: <dense requires clause>;
ensures: <dense ensures clause>;
```
"""
