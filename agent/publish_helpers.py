"""Seam-free pure helpers for the publish pipeline.

These are spec-validation and module-name sanitization utilities extracted
verbatim from :mod:`agent.publish`.  They read no patched collaborators and
touch no module-global ``subprocess`` / ``shutil`` seams, so they live here
while the driver (``publish``), git helpers (``_git`` /
``_ensure_git_identity``), and the GitHub PR helper (``_create_github_pr``)
remain in the façade.
"""

from __future__ import annotations

import re

# Only allow alphanumeric, hyphen, underscore, and dot in module names.
# The first character must NOT be a hyphen to prevent filenames like "-A.mm"
# from being misinterpreted as command-line flags by git or other tools.
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_\.][A-Za-z0-9_\-\.]*$")


def _validate_spec(spec: dict) -> str | None:
    """Validate a spec dict, returning an error message or None if valid.

    Mirrors the checks in ``agent.generate._validate_spec`` but returns
    an error string instead of calling ``sys.exit``.
    """
    if "atoms" in spec:
        atoms = spec["atoms"]
        if not isinstance(atoms, list) or len(atoms) == 0:
            return "Multi-atom spec 'atoms' must be a non-empty list."
        for i, atom in enumerate(atoms):
            if not isinstance(atom, dict) or "name" not in atom:
                return f"atoms[{i}] must be a dict with a 'name' key."
    else:
        if "name" not in spec:
            return "Single-atom spec must have a 'name' key."
    return None


def _sanitize_module_name(raw: str) -> str:
    """Sanitize a module name for use in file paths and branch names.

    Raises ``ValueError`` if the name is empty, contains unsafe characters,
    includes ``..`` (invalid in git ref names), or ends with ``.lock``
    (rejected by git).
    """
    if not raw or not _SAFE_NAME_RE.match(raw):
        raise ValueError(
            f"Unsafe module name {raw!r}. "
            "Only alphanumeric characters, hyphens, underscores, and dots are allowed."
        )
    if ".." in raw:
        raise ValueError(
            f"Unsafe module name {raw!r}. "
            "Consecutive dots ('..') are not allowed (invalid in git branch names)."
        )
    if raw.startswith(".") or raw.endswith("."):
        raise ValueError(
            f"Unsafe module name {raw!r}. "
            "Names starting or ending with a dot are not allowed "
            "(invalid in git branch names)."
        )
    if raw.endswith(".lock"):
        raise ValueError(
            f"Unsafe module name {raw!r}. "
            "Names ending with '.lock' are not allowed (invalid in git branch names)."
        )
    return raw
