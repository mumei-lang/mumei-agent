"""Loss/dict numeric utilities for the self-correction strategy."""
from __future__ import annotations


def _dict_get(value: object, key: str) -> object | None:
    if isinstance(value, dict):
        return value.get(key)
    return None


def _numeric_zero(value: object) -> bool:
    try:
        return abs(float(value)) <= 1e-9
    except (TypeError, ValueError):
        return False
