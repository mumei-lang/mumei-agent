"""System prompt for the forge (Mumei Master Blacksmith) mode.

The forge mode autonomously extends the mumei standard library (`std/*.mm`)
with new verified atoms.  Prompts produced here instruct the LLM to act as
a careful blacksmith who forges new atoms consistent with the existing
standard library's style, contracts, and naming conventions.
"""
from __future__ import annotations

FORGE_SYSTEM_PROMPT = (
    "You are the Mumei Master Blacksmith (鍛冶職人).  "
    "Your sole responsibility is to forge new, formally verified atoms "
    "for the mumei standard library.\n\n"
    "Mumei is a proof-driven language: every atom must have a "
    "`requires` precondition, an `ensures` postcondition, and a body "
    "whose return value satisfies `ensures` for all inputs satisfying "
    "`requires`.  The Z3 SMT solver will reject anything that cannot be "
    "proven correct.\n\n"
    "Hard rules (violating any of these is failure):\n"
    "1. Match the style of the surrounding standard library file "
    "   (indentation, clause ordering, comment language, naming).\n"
    "2. Contracts (`requires` / `ensures`) must be total — they must "
    "   cover every input the body can receive.\n"
    "3. Prefer the strongest possible `requires` that keeps the atom "
    "   useful.  Overflow, division-by-zero, and negative-result cases "
    "   must be excluded via `requires`, not patched in the body.\n"
    "4. The body should be a direct, verifiable computation.  Do not "
    "   call out to effects unless the spec declares them.\n"
    "5. Produce ONLY the new atom(s).  Do not re-emit any existing "
    "   atoms.  Do not emit explanatory prose outside the code fence.\n"
    "6. Do not invent new operators, types, or syntax.  Use only what "
    "   the surrounding file already uses.\n"
)


def build_reference_context(existing_source: str, reference_patterns: list[str]) -> str:
    """Extract the code of specified atoms from *existing_source*.

    The forge prompt injects these as style/contract examples so the
    LLM mirrors the standard library's conventions.

    Parameters
    ----------
    existing_source:
        Full contents of the target `.mm` file.
    reference_patterns:
        Names of existing atoms whose code should be surfaced.

    Returns
    -------
    A formatted string containing the matched atom blocks, or an empty
    string if no matches are found.
    """
    if not existing_source or not reference_patterns:
        return ""

    lines = existing_source.splitlines()
    blocks: list[str] = []

    for name in reference_patterns:
        block = _extract_atom_block(lines, name)
        if block:
            blocks.append(f"### Reference atom: `{name}`\n```mumei\n{block}\n```")

    if not blocks:
        return ""

    return (
        "# Style context — existing atoms from the target file.\n"
        "# Match their indentation, clause ordering, and comment style.\n\n"
        + "\n\n".join(blocks)
    )


def _extract_atom_block(lines: list[str], name: str) -> str:
    """Extract the code block for atom *name* from a split-by-line source."""
    start: int | None = None
    for idx, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith(f"atom {name}(") or stripped.startswith(f"atom {name} ("):
            start = idx
            break
    if start is None:
        return ""

    # Find the end of the block: the atom definition runs until the next
    # line that ends with `;` at column 0 (end-of-atom terminator in the
    # existing std/contracts.mm style), or until the next `atom ` / EOF.
    end = len(lines)
    depth = 0
    for idx in range(start, len(lines)):
        line = lines[idx]
        depth += line.count("{") - line.count("}")
        stripped = line.rstrip()
        # Terminate on trailing `;` once braces are balanced and we're past the opener.
        if idx > start and depth <= 0 and stripped.endswith(";"):
            end = idx + 1
            break
        # Safety: don't run into the next atom.
        if idx > start and line.lstrip().startswith("atom "):
            end = idx
            break

    return "\n".join(lines[start:end])
