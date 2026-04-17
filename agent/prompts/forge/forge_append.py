"""Prompt builder for forge mode — append variant.

Produces a user-message prompt that asks the LLM to generate ONLY the
new atom(s) to append to an existing `.mm` file, given the existing
source as style context.
"""
from __future__ import annotations

import json

from agent.prompts.forge.forge_system import build_reference_context


def build_append_prompt(
    task: dict,
    existing_source: str,
    *,
    last_error: str | None = None,
    last_snippet: str | None = None,
) -> str:
    """Build the user message for an ``append``-mode forge task.

    Parameters
    ----------
    task:
        The parsed forge task spec.
    existing_source:
        Current contents of the target `.mm` file.
    last_error:
        When retrying after a check/verify failure, the stderr or error
        log from the previous attempt.  Injected as a "fix this" section
        so the LLM can learn from the failure instead of regenerating
        blindly.
    last_snippet:
        The code snippet that was generated on the previous (failed)
        attempt, so the LLM can see exactly what went wrong.
    """
    atoms = task.get("atoms") or []
    reference_patterns = _collect_reference_patterns(atoms)

    sections: list[str] = []

    target_file = task.get("target_file", "<unknown>")
    sections.append(
        f"# Forge task: `{task.get('task_id', 'unknown')}`\n"
        f"Target file: `{target_file}` (mode: append).\n"
        "Append only the new atom(s) listed below.  Do not re-emit any "
        "existing code from the target file."
    )

    if existing_source.strip():
        tail = _tail_lines(existing_source, 80)
        sections.append(
            "# Tail of the target file (for style matching).\n"
            "# Your output will be appended directly after this.\n"
            f"```mumei\n{tail}\n```"
        )

    ref_block = build_reference_context(existing_source, reference_patterns)
    if ref_block:
        sections.append(ref_block)

    sections.append(
        "# Atom specification(s) to forge:\n"
        f"```json\n{json.dumps(atoms, indent=2, ensure_ascii=False)}\n```"
    )

    if last_error and last_snippet:
        sections.append(
            "# Previous attempt (FAILED — do NOT repeat the same mistake).\n"
            f"```mumei\n{last_snippet.strip()}\n```\n\n"
            "# Verifier / parser error from the previous attempt:\n"
            f"```\n{last_error.strip()[:1000]}\n```\n\n"
            "Analyse the error above and produce a corrected version."
        )
    elif last_error:
        sections.append(
            "# Verifier / parser error from the previous attempt:\n"
            f"```\n{last_error.strip()[:1000]}\n```\n\n"
            "Analyse the error above and avoid the same mistake."
        )

    sections.append(
        "Output ONLY the new atom definition(s) inside a single "
        "```mumei ...``` fenced code block.  Do not include imports, "
        "extern declarations, or any existing atom definitions."
    )

    return "\n\n".join(sections)


def _collect_reference_patterns(atoms: list[dict]) -> list[str]:
    """Collect (de-duplicated, order-preserving) reference patterns from atoms."""
    seen: set[str] = set()
    out: list[str] = []
    for atom in atoms:
        patterns = atom.get("reference_patterns") or []
        if not isinstance(patterns, list):
            continue
        for name in patterns:
            if isinstance(name, str) and name and name not in seen:
                seen.add(name)
                out.append(name)
    return out


def _tail_lines(source: str, n: int) -> str:
    """Return the last *n* lines of *source*."""
    lines = source.splitlines()
    if len(lines) <= n:
        return source.rstrip()
    return "\n".join(lines[-n:]).rstrip()
