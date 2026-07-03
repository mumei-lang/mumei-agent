"""Helper utilities for rule-based deterministic fixes.

These functions perform the regex-based source manipulation and the
individual deterministic fix implementations used by
:func:`agent.strategies.rule_based_fix.try_rule_based_fix`.
"""
from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _scoped_block(source: str, start: int) -> str:
    """Return the slice of *source* from *start* up to the next atom boundary.

    This prevents regex helpers from accidentally matching clauses that
    belong to a subsequent atom in multi-atom files.
    """
    rest = source[start:]
    # Look for the next top-level ``atom`` keyword (preceded by a newline
    # to avoid matching the word inside identifiers or strings).
    next_atom = re.search(r'\natom\s', rest)
    if next_atom is not None:
        return rest[:next_atom.start()]
    return rest


def _find_atom_requires(source: str, atom_name: str) -> tuple[int, int, str] | None:
    """Find the start/end position and current value of the requires clause.

    Returns ``(start, end, value)`` where *value* is the text after
    ``requires:`` (e.g. ``"true"`` or ``"a > 0"``).  Returns ``None``
    when the atom or its requires clause cannot be located.

    See :func:`_find_atom_declaration_end` for a note on the nested
    parentheses limitation of the atom declaration regex.
    """
    # Match the atom declaration line
    atom_pattern = re.compile(
        rf'atom\s+{re.escape(atom_name)}\s*\(.*?\)',
        re.DOTALL,
    )
    atom_match = atom_pattern.search(source)
    if atom_match is None:
        return None

    # Search for `requires:` after the atom declaration, scoped to this atom
    rest = _scoped_block(source, atom_match.end())
    req_match = re.search(r'requires\s*:\s*(.+?)\s*;', rest)
    if req_match is None:
        return None

    start = atom_match.end() + req_match.start(1)
    end = atom_match.end() + req_match.end(1)
    value = req_match.group(1).strip()
    return start, end, value


def _append_to_requires(source: str, atom_name: str, new_constraint: str) -> str | None:
    """Add a constraint to an atom's requires clause.

    If ``requires: true``, replaces it with the new constraint.
    Otherwise appends ``&& <new_constraint>``.
    Returns ``None`` if the requires clause cannot be found.
    """
    result = _find_atom_requires(source, atom_name)
    if result is None:
        return None
    start, end, value = result

    if value == "true":
        new_value = new_constraint
    else:
        new_value = f"{value} && {new_constraint}"
    return source[:start] + new_value + source[end:]


def _find_atom_effects(source: str, atom_name: str) -> tuple[int, int, list[str]] | None:
    """Find the effects declaration for a given atom.

    Returns ``(start, end, effects_list)`` where *start*/*end* mark the
    full ``effects: [...]`` token (including brackets) and *effects_list*
    contains the individual effect names.  Returns ``None`` when the
    atom or its effects clause cannot be located.

    See :func:`_find_atom_declaration_end` for a note on the nested
    parentheses limitation of the atom declaration regex.
    """
    atom_pattern = re.compile(
        rf'atom\s+{re.escape(atom_name)}\s*\(.*?\)',
        re.DOTALL,
    )
    atom_match = atom_pattern.search(source)
    if atom_match is None:
        return None

    rest = _scoped_block(source, atom_match.end())
    eff_match = re.search(r'effects\s*:\s*\[([^\]]*)\]', rest)
    if eff_match is None:
        return None

    start = atom_match.end() + eff_match.start()
    end = atom_match.end() + eff_match.end()
    effects_str = eff_match.group(1).strip()
    effects_list = [e.strip() for e in effects_str.split(",") if e.strip()]
    return start, end, effects_list


def _find_atom_declaration_end(source: str, atom_name: str) -> int | None:
    """Return the position right after the atom's closing parenthesis.

    Note: the ``\\(.*?\\)`` pattern uses a non-greedy match that stops at
    the first ``)``.  This works for Mumei's current simple type syntax
    (e.g. ``i64``, ``Str``) but would break if nested parentheses were
    introduced in parameter types (e.g. ``Pair(i64, i64)``).
    """
    atom_pattern = re.compile(
        rf'atom\s+{re.escape(atom_name)}\s*\(.*?\)',
        re.DOTALL,
    )
    atom_match = atom_pattern.search(source)
    if atom_match is None:
        return None
    return atom_match.end()


# ---------------------------------------------------------------------------
# Fix implementations
# ---------------------------------------------------------------------------

def _fix_division_by_zero(source_code: str, report: dict) -> str | None:
    """Add a ``!= 0`` precondition for the divisor parameter."""
    atom_name = report.get("atom", "")
    if not atom_name:
        return None

    # Determine the divisor parameter name.
    #
    # Strategy:
    #   1. If semantic_feedback.counter_example has a "divisor" key with
    #      value "0", use its corresponding actual parameter name from the
    #      top-level counterexample (matched by position) or fall back to
    #      the semantic key itself.
    #   2. From the top-level counterexample, collect all params whose
    #      value is "0".  If exactly one is zero, use it.  If multiple
    #      are zero, pick the *last* one — in ``a / b`` style expressions
    #      the divisor is typically the last parameter.
    #   3. If the top-level counterexample is absent, apply the same
    #      logic to semantic_feedback.counter_example.
    divisor_param: str | None = None

    semantic = report.get("semantic_feedback", {})
    sem_ce = semantic.get("counter_example", {})
    top_ce = report.get("counterexample", {})

    # 1. Explicit "divisor" key in semantic feedback
    if "divisor" in sem_ce and str(sem_ce["divisor"]) == "0":
        # Try to map back to the actual parameter name via top-level CE
        # (semantic CE keys are role names, not param names).
        zero_params = [k for k, v in top_ce.items() if str(v) == "0"]
        if len(zero_params) == 1:
            divisor_param = zero_params[0]
        elif zero_params:
            divisor_param = zero_params[-1]
        else:
            divisor_param = "divisor"  # use semantic key as last resort

    # 2. Top-level counterexample (actual param names)
    if divisor_param is None and top_ce:
        zero_params = [k for k, v in top_ce.items() if str(v) == "0"]
        if len(zero_params) == 1:
            divisor_param = zero_params[0]
        elif zero_params:
            # Multiple zeros — pick the last param (likely the divisor)
            divisor_param = zero_params[-1]

    # 3. Fallback: semantic_feedback.counter_example
    if divisor_param is None:
        zero_params = [k for k, v in sem_ce.items() if str(v) == "0"]
        if len(zero_params) == 1:
            divisor_param = zero_params[0]
        elif zero_params:
            divisor_param = zero_params[-1]

    if divisor_param is None:
        return None

    constraint = f"{divisor_param} != 0"

    # Check if requires clause exists
    result = _find_atom_requires(source_code, atom_name)
    if result is None:
        return None

    return _append_to_requires(source_code, atom_name, constraint)


def _fix_effect_mismatch(source_code: str, report: dict) -> str | None:
    """Add a missing effect to an atom's effects list."""
    effect_violation = report.get("effect_violation", {})
    required_effect = effect_violation.get("required_effect", "")
    if not required_effect:
        return None

    atom_name = report.get("atom", "")
    if not atom_name:
        return None

    eff_result = _find_atom_effects(source_code, atom_name)
    if eff_result is not None:
        start, end, effects_list = eff_result
        if required_effect in effects_list:
            return None  # already declared
        effects_list.append(required_effect)
        new_effects = f"effects: [{', '.join(effects_list)}]"
        return source_code[:start] + new_effects + source_code[end:]

    # No effects line exists — insert one after the atom declaration
    decl_end = _find_atom_declaration_end(source_code, atom_name)
    if decl_end is None:
        return None

    # Detect indentation from the next line
    rest = source_code[decl_end:]
    indent_match = re.match(r'\n(\s+)', rest)
    indent = indent_match.group(1) if indent_match else "    "

    insertion = f"\n{indent}effects: [{required_effect}]"
    return source_code[:decl_end] + insertion + source_code[decl_end:]


def _fix_effect_propagation(source_code: str, report: dict) -> str | None:
    """Add missing effects to a caller atom's effects list."""
    effect_violation = report.get("effect_violation", {})
    missing_effects = effect_violation.get("missing_effects", [])
    caller = effect_violation.get("caller", "")
    if not missing_effects or not caller:
        return None

    eff_result = _find_atom_effects(source_code, caller)
    if eff_result is not None:
        start, end, effects_list = eff_result
        added = False
        for eff in missing_effects:
            if eff not in effects_list:
                effects_list.append(eff)
                added = True
        if not added:
            return None  # all effects already present
        new_effects = f"effects: [{', '.join(effects_list)}]"
        return source_code[:start] + new_effects + source_code[end:]

    # No effects line exists — insert one after the caller's declaration
    decl_end = _find_atom_declaration_end(source_code, caller)
    if decl_end is None:
        return None

    rest = source_code[decl_end:]
    indent_match = re.match(r'\n(\s+)', rest)
    indent = indent_match.group(1) if indent_match else "    "

    insertion = f"\n{indent}effects: [{', '.join(missing_effects)}]"
    return source_code[:decl_end] + insertion + source_code[decl_end:]


def _fix_postcondition_violated(source_code: str, report: dict) -> str | None:
    """Wrap body expression in a guard when ensures constraint is violated.

    When ``failure_type == "postcondition_violated"`` and the ensures clause
    contains ``result >= 0``, wrap the body expression in
    ``if expr >= 0 { expr } else { 0 }`` to satisfy the postcondition.
    """
    atom_name = report.get("atom", "")
    if not atom_name:
        return None

    # Check if ensures contains "result >= 0"
    atom_pattern = re.compile(
        rf'atom\s+{re.escape(atom_name)}\s*\(.*?\)',
        re.DOTALL,
    )
    atom_match = atom_pattern.search(source_code)
    if atom_match is None:
        return None

    rest = _scoped_block(source_code, atom_match.end())
    ensures_match = re.search(r'ensures\s*:\s*(.+?)\s*;', rest)
    if ensures_match is None:
        return None

    ensures_value = ensures_match.group(1).strip()
    if "result >= 0" not in ensures_value:
        return None

    # Find the body expression
    body_match = re.search(r'body\s*:\s*\{([^}]+)\}', rest)
    if body_match is None:
        # Try single-expression body: body: <expr>;
        body_match = re.search(r'body\s*:\s*(.+?)\s*;', rest)
        if body_match is None:
            return None
        expr = body_match.group(1).strip()
        abs_start = atom_match.end() + body_match.start(1)
        abs_end = atom_match.end() + body_match.end(1)
        new_expr = f"{{ let __tmp = {expr}; if __tmp >= 0 {{ __tmp }} else {{ 0 }} }}"
        return source_code[:abs_start] + new_expr + source_code[abs_end:]

    expr = body_match.group(1).strip()
    abs_start = atom_match.end() + body_match.start(1)
    abs_end = atom_match.end() + body_match.end(1)
    new_expr = f"\n        let __tmp = {expr};\n        if __tmp >= 0 {{ __tmp }} else {{ 0 }}\n    "
    return source_code[:abs_start] + new_expr + source_code[abs_end:]


def _fix_invariant_violated(source_code: str, report: dict) -> str | None:
    """Add bounds check for struct field invariant violations.

    When ``violation_type == "invariant_violated"``, extract the struct field
    and constraint from the report and add a bounds check before the
    violating assignment.
    """
    atom_name = report.get("atom", "")
    if not atom_name:
        return None

    semantic = report.get("semantic_feedback", {})
    violated = semantic.get("violated_constraints", [])
    if not violated:
        return None

    # Scope the search to the target atom's body
    atom_pattern = re.compile(
        rf'atom\s+{re.escape(atom_name)}\s*\(.*?\)',
        re.DOTALL,
    )
    atom_match = atom_pattern.search(source_code)
    if atom_match is None:
        return None

    rest = _scoped_block(source_code, atom_match.end())

    for entry in violated:
        field_name = entry.get("field", entry.get("param", ""))
        constraint = entry.get("constraint", "")
        if not field_name or not constraint:
            continue

        # Try to add a guard: clamp to bounds if constraint is "field >= N"
        lower_match = re.match(rf'{re.escape(field_name)}\s*>=\s*(\w+)', constraint)
        if lower_match:
            bound = lower_match.group(1)
            # Find assignment to the field within the scoped atom body
            # Use =(?!=) to avoid matching == comparisons
            assign_pattern = re.compile(
                rf'({re.escape(field_name)}\s*=(?!=)\s*)([^;]+)(;)',
            )
            assign_match = assign_pattern.search(rest)
            if assign_match:
                expr = assign_match.group(2).strip()
                new_expr = f"if {expr} >= {bound} {{ {expr} }} else {{ {bound} }}"
                abs_start = atom_match.end() + assign_match.start(2)
                abs_end = atom_match.end() + assign_match.end(2)
                return (
                    source_code[:abs_start]
                    + new_expr
                    + source_code[abs_end:]
                )

    return None


def _fix_linearity_violated(source_code: str, report: dict) -> str | None:
    """Comment out the second usage of a linear resource.

    When ``violation_type == "linearity_violated"``, extract the resource
    name from the report's semantic_feedback and comment out or remove the
    second usage of the linear resource.
    """
    atom_name = report.get("atom", "")
    semantic = report.get("semantic_feedback", {})
    resource_name = semantic.get("resource", "")
    if not resource_name:
        # Try to extract from violated_constraints or message
        msg = report.get("message", semantic.get("message", ""))
        resource_match = re.search(r"resource '(\w+)'", msg)
        if resource_match:
            resource_name = resource_match.group(1)
        else:
            # Try extracting variable name from the report
            resource_name = semantic.get("variable", "")
    if not resource_name:
        return None

    # Scope the search to the target atom's body when atom_name is available
    offset = 0
    search_text = source_code
    if atom_name:
        atom_pattern = re.compile(
            rf'atom\s+{re.escape(atom_name)}\s*\(.*?\)',
            re.DOTALL,
        )
        atom_match = atom_pattern.search(source_code)
        if atom_match is not None:
            scoped = _scoped_block(source_code, atom_match.end())
            # Narrow further to just the body block so that references in
            # requires:/ensures:/effects: clauses are not counted as usages.
            body_start = re.search(r'body\s*:', scoped)
            if body_start is not None:
                offset = atom_match.end() + body_start.start()
                search_text = scoped[body_start.start():]
            else:
                offset = atom_match.end()
                search_text = scoped

    # Find all usages of the resource in the body text
    usage_pattern = re.compile(
        rf'\b{re.escape(resource_name)}\b',
    )
    matches = list(usage_pattern.finditer(search_text))
    if len(matches) < 2:
        return None

    # Comment out the last usage line
    last_match = matches[-1]
    # Translate back to absolute positions in source_code
    abs_start_match = offset + last_match.start()
    abs_end_match = offset + last_match.end()
    # Find the line containing the last match
    line_start = source_code.rfind('\n', 0, abs_start_match) + 1
    line_end = source_code.find('\n', abs_end_match)
    if line_end == -1:
        line_end = len(source_code)

    line = source_code[line_start:line_end]
    # Skip if this is the declaration or requires/ensures line
    stripped = line.strip()
    if stripped.startswith(('atom ', 'requires:', 'ensures:', 'type ', 'struct ')):
        return None

    commented_line = line.replace(stripped, f"// {stripped} // linearity fix: removed duplicate use")
    return source_code[:line_start] + commented_line + source_code[line_end:]


def _fix_precondition(source_code: str, report: dict) -> str | None:
    """Add violated constraints to the atom's requires clause.

    Only applies when each constraint is a simple comparison
    (``\\w+ [<>=!]+ \\w+``).
    """
    atom_name = report.get("atom", "")
    if not atom_name:
        return None

    semantic = report.get("semantic_feedback", {})
    violated = semantic.get("violated_constraints", [])
    if not violated:
        return None

    simple_cmp = re.compile(r'^\w+\s*[<>=!]+\s*\w+$')

    modified = source_code
    for entry in violated:
        constraint = entry.get("constraint", "")
        if not constraint or not simple_cmp.match(constraint):
            continue

        # Check if constraint is already in the requires clause
        req = _find_atom_requires(modified, atom_name)
        if req is None:
            return None
        _start, _end, current_value = req
        if constraint in current_value:
            continue

        result = _append_to_requires(modified, atom_name, constraint)
        if result is None:
            return None
        modified = result

    # Only return if we actually changed something
    if modified == source_code:
        return None
    return modified
