"""Cache and diff helpers for proliferation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def _safe_relative_file(repo_dir: Path, rel_path: str) -> Path | None:
    candidate = (repo_dir / rel_path).resolve()
    try:
        candidate.relative_to(repo_dir.resolve())
    except ValueError:
        return None
    return candidate


# Spec fields that only affect queue ordering, never generated code.
_NON_GENERATION_SPEC_FIELDS = ("priority", "benchmark_feedback")


def _spec_cache_key(
    spec: dict[str, Any],
    mumei_repo_dir: Path | None = None,
) -> str:
    keyed_spec = {
        key: value
        for key, value in spec.items()
        if key not in _NON_GENERATION_SPEC_FIELDS
    }
    payload_obj: dict[str, Any] = {"spec": keyed_spec}
    if mumei_repo_dir is not None:
        context_hashes: dict[str, str | None] = {}
        rel_paths: set[str] = set()
        for key in ("target_file",):
            value = keyed_spec.get(key)
            if isinstance(value, str):
                rel_paths.add(value)
        for key in ("context_files", "depends_on"):
            value = keyed_spec.get(key)
            if isinstance(value, list):
                rel_paths.update(item for item in value if isinstance(item, str))
        for rel_path in sorted(rel_paths):
            candidate = _safe_relative_file(mumei_repo_dir, rel_path)
            if candidate is not None and candidate.is_file():
                try:
                    context_hashes[rel_path] = hashlib.sha256(
                        candidate.read_bytes()
                    ).hexdigest()
                except OSError:
                    context_hashes[rel_path] = None
            else:
                context_hashes[rel_path] = None
        payload_obj["context_hashes"] = context_hashes
    payload = json.dumps(payload_obj, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _forge_cache_path(mumei_repo_dir: Path) -> Path:
    return mumei_repo_dir / ".mumei" / "proliferate_forge_cache.json"


def _detect_diffs(
    mumei_repo_dir: str | Path,
    target_file: str | Path,
    code: str,
) -> dict[str, Any]:
    """Return content-level diff metadata for a generated target file."""
    path = Path(mumei_repo_dir) / target_file
    existing = path.read_text(encoding="utf-8") if path.exists() else None
    old_hash = (
        hashlib.sha256(existing.encode("utf-8")).hexdigest()
        if existing is not None
        else None
    )
    new_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
    return {
        "target_file": str(target_file),
        "exists": existing is not None,
        "changed": existing != code,
        "old_sha256": old_hash,
        "new_sha256": new_hash,
    }
