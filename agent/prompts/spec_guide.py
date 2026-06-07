"""Shared SPEC_GUIDE.md decidable-fragment guideline constants.

Both ``generate_atom`` and ``spec_extraction`` import from here to
avoid maintaining duplicate copies of the same guidance text.
"""

SPEC_GUIDE_DECIDABLE_FRAGMENT = (
    "SPEC_GUIDE.md decidable-fragment rules for generated specs:\n"
    "- Prefer linear i64/Nat arithmetic: addition, subtraction, comparisons, and constant multiplication.\n"
    "- Avoid variable-variable multiplication/division/modulo and exponentiation; mark such requirements as Lean escalation candidates if essential.\n"
    "- For every array access `a[i]`, include `0 <= i && i < len(a)` in `requires` or a bounded `forall`.\n"
    "- Use `forall` only over bounded ranges or finite collections; avoid `forall exists` / `exists forall` alternation.\n"
    "- Prefer constructible witnesses over existential postconditions.\n"
    "- Model temporal behavior as explicit finite-state transitions.\n"
    "- Avoid nested mutable aliasing and regex constraints (`regex_match`, `re_match`) unless the requirement explicitly needs them.\n"
    "- If verification reports `outside_decidable_fragment`, first simplify the spec before changing implementation code.\n"
)
