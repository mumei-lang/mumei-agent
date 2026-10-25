"""Safe loading of cross-module Mumei context files."""
from __future__ import annotations

import logging
from pathlib import Path

_logger = logging.getLogger(__name__)


def load_context_files(context_files: object, repo_dir: Path) -> str:
    """Load and format context files confined to a Mumei repository."""
    if not context_files:
        return ""
    if not isinstance(context_files, list):
        return ""

    repo_root = Path(repo_dir).resolve()
    sections: list[str] = []
    for rel_path in context_files:
        if not isinstance(rel_path, str) or not rel_path:
            continue
        full_path = (repo_root / rel_path).resolve()
        try:
            full_path.relative_to(repo_root)
        except ValueError:
            _logger.warning("context_file escapes repo root: %s", rel_path)
            continue
        if not full_path.exists() or not full_path.is_file():
            _logger.warning("context_file not found: %s", rel_path)
            continue
        try:
            content = full_path.read_text(encoding="utf-8")
        except OSError as exc:
            _logger.warning("Failed to read context_file %s: %s", rel_path, exc)
            continue
        sections.append(
            f"# Context file: `{rel_path}`\n"
            f"```mumei\n{content.strip()}\n```"
        )

    if not sections:
        return ""
    return (
        "# Cross-file context — related std modules.\n"
        "# Use these contracts and types as style references.  Do NOT "
        "re-emit them.\n\n"
        + "\n\n".join(sections)
    )
