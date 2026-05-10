"""Prompt builder for high-density Mumei property generation."""
from __future__ import annotations

from typing import Any


def build_dense_property_prompt(
    spec: dict[str, Any],
    current_properties: dict[str, Any],
) -> str:
    """Build the prompt used to synthesize compact contracts."""
    return f"""# Generate High-Density Properties

## Specification
{spec}

## Current Properties
Requires: {current_properties.get("requires", [])}
Ensures: {current_properties.get("ensures", [])}

## Instructions
Generate high-density, mathematically precise requires/ensures clauses that:
1. Capture all semantic constraints from the specification
2. Use minimal tokens while maintaining mathematical precision
3. Leverage Mumei's effect system and type system
4. Are optimized for Z3 verification efficiency

Output format:
```mumei
requires: <high-density requires clause>;
ensures: <high-density ensures clause>;
```
"""
