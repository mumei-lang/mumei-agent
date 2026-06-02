"""Decode latent feature vectors back into conservative Mumei code edits."""
from __future__ import annotations

from collections.abc import Mapping
import re

import numpy as np


REQUIRES_STRENGTHEN_INDEX = 5
ENSURES_WEAKEN_INDEX = 6
EFFECT_ADD_INDEX = 10
EFFECT_REMOVE_INDEX = 11
TYPE_REFINE_INDEX = 12
LOOP_INVARIANT_INDEX = 13
ASSERTION_ADD_INDEX = 14
VARIABLE_REFACTOR_INDEX = 15


class LatentDecoder:
    """Mumei-specific NLAE-inspired latent decoder."""

    def decode_to_source(
        self,
        latent_vector: np.ndarray,
        original_code: str,
        repair_context: Mapping[str, object] | None = None,
    ) -> str:
        """Decode a latent vector into source while preserving structure."""
        return self._apply_latent_changes(
            original_code,
            latent_vector,
            repair_context or {},
        )

    def _apply_latent_changes(
        self,
        original_code: str,
        latent_vector: np.ndarray,
        repair_context: Mapping[str, object],
    ) -> str:
        """Apply conservative latent edits that can safely fall back."""
        atom_name = self._context_string(repair_context, "atom")
        if len(latent_vector) > EFFECT_ADD_INDEX and latent_vector[EFFECT_ADD_INDEX] > 0.5:
            effect_name = self._context_string(repair_context, "effect_name") or "Write"
            return self._add_effect(original_code, effect_name, atom_name)
        if len(latent_vector) > EFFECT_REMOVE_INDEX and latent_vector[EFFECT_REMOVE_INDEX] > 0.5:
            effect_name = self._context_string(repair_context, "effect_to_remove")
            return self._remove_first_effect(original_code, atom_name, effect_name)
        if len(latent_vector) > LOOP_INVARIANT_INDEX and latent_vector[LOOP_INVARIANT_INDEX] > 0.5:
            invariant = self._context_string(repair_context, "loop_invariant") or "true"
            return self._insert_loop_invariant(original_code, invariant, atom_name)
        if len(latent_vector) > ASSERTION_ADD_INDEX and latent_vector[ASSERTION_ADD_INDEX] > 0.5:
            assertion = self._context_string(repair_context, "assertion") or "true"
            return self._add_assertion(original_code, assertion, atom_name)
        if (
            len(latent_vector) > VARIABLE_REFACTOR_INDEX
            and latent_vector[VARIABLE_REFACTOR_INDEX] > 0.5
        ):
            rename_map = self._context_mapping(repair_context, "rename_map")
            return self._refactor_variable_names(original_code, rename_map, atom_name)
        if len(latent_vector) > TYPE_REFINE_INDEX and latent_vector[TYPE_REFINE_INDEX] > 0.5:
            target_name = self._context_string(repair_context, "type_target")
            return self._refine_i64_types(original_code, target_name)
        if (
            len(latent_vector) > REQUIRES_STRENGTHEN_INDEX
            and latent_vector[REQUIRES_STRENGTHEN_INDEX] > 0.5
        ):
            constraint = self._context_string(repair_context, "requires_constraint")
            return self._strengthen_first_requires(original_code, constraint, atom_name)
        if len(latent_vector) > ENSURES_WEAKEN_INDEX and latent_vector[ENSURES_WEAKEN_INDEX] > 0.5:
            return self._weaken_ensures(original_code, atom_name)
        return original_code

    def _context_string(self, repair_context: Mapping[str, object], key: str) -> str:
        value = repair_context.get(key)
        if isinstance(value, str):
            return value.strip()
        return ""

    def _context_mapping(
        self,
        repair_context: Mapping[str, object],
        key: str,
    ) -> dict[str, str]:
        value = repair_context.get(key)
        if not isinstance(value, Mapping):
            return {}
        mapped: dict[str, str] = {}
        for old_name, new_name in value.items():
            if isinstance(old_name, str) and isinstance(new_name, str):
                clean_old = old_name.strip()
                clean_new = new_name.strip()
                if clean_old and clean_new:
                    mapped[clean_old] = clean_new
        return mapped

    def _strengthen_first_requires(
        self,
        source_code: str,
        constraint: str = "",
        atom_name: str = "",
    ) -> str:
        """Strengthen a requires clause with a verifier-derived constraint."""
        new_constraint = constraint.strip() or "true"
        span = self._find_clause_span(source_code, "requires", atom_name)
        if span is None:
            return self._insert_clause_after_atom(
                source_code,
                "requires",
                new_constraint,
                atom_name,
            )
        start, end, value = span
        if self._contains_constraint(value, new_constraint):
            return source_code
        if value.strip() == "true":
            updated = new_constraint
        elif new_constraint == "true":
            updated = f"({value.strip()}) && true"
        else:
            updated = f"({value.strip()}) && {new_constraint}"
        return source_code[:start] + updated + source_code[end:]

    def _weaken_ensures(self, source_code: str, atom_name: str = "") -> str:
        """Weaken an ensures clause by removing or relaxing one conjunct."""
        span = self._find_clause_span(source_code, "ensures", atom_name)
        if span is None:
            return source_code
        start, end, value = span
        return source_code[:start] + self._weaken_expression(value) + source_code[end:]

    def _weaken_expression(self, expression: str) -> str:
        conjuncts = self._split_top_level_conjuncts(expression)
        if len(conjuncts) > 1:
            return " && ".join([*conjuncts[:-1], "true"])
        stripped = expression.strip()
        strict_lower = re.search(r"\bresult\s*>\s*(.+)$", stripped)
        if strict_lower is not None:
            return f"result >= {strict_lower.group(1).strip()}"
        strict_upper = re.search(r"\bresult\s*<\s*(.+)$", stripped)
        if strict_upper is not None:
            return f"result <= {strict_upper.group(1).strip()}"
        return stripped

    def _split_top_level_conjuncts(self, expression: str) -> list[str]:
        conjuncts: list[str] = []
        start = 0
        depth = 0
        i = 0
        while i < len(expression):
            char = expression[i]
            if char == "(":
                depth += 1
            elif char == ")":
                depth = max(0, depth - 1)
            elif expression.startswith("&&", i) and depth == 0:
                part = expression[start:i].strip()
                if part:
                    conjuncts.append(part)
                i += 2
                start = i
                continue
            i += 1
        tail = expression[start:].strip()
        if tail:
            conjuncts.append(tail)
        return conjuncts

    def _add_effect(
        self,
        source_code: str,
        effect_name: str,
        atom_name: str = "",
    ) -> str:
        """Add an effect to an atom effects clause or create one."""
        selected = effect_name.strip() or "Write"
        scoped = self._scoped_region(source_code, atom_name)
        effects_match = re.search(r"(effects\s*:\s*\[)([^\]]*)(\])", scoped.text)
        if effects_match:
            existing = [
                effect.strip()
                for effect in effects_match.group(2).split(",")
                if effect.strip()
            ]
            selected = self._choose_effect_name(selected, existing)
            if selected in existing:
                return source_code
            updated = ", ".join([*existing, selected])
            abs_start = scoped.offset + effects_match.start()
            abs_end = scoped.offset + effects_match.end()
            return (
                source_code[:abs_start]
                + f"{effects_match.group(1)}{updated}{effects_match.group(3)}"
                + source_code[abs_end:]
            )
        return self._insert_clause_after_atom(
            source_code,
            "effects",
            f"[{selected}]",
            atom_name,
        )

    def _choose_effect_name(self, fallback: str, existing: list[str]) -> str:
        if fallback:
            return fallback
        for effect in existing:
            words = effect.split()
            if len(words) > 1:
                return words[0]
        return "Write"

    def _remove_first_effect(
        self,
        source_code: str,
        atom_name: str = "",
        effect_name: str = "",
    ) -> str:
        """Remove one effect entry from an effects clause."""
        scoped = self._scoped_region(source_code, atom_name)

        def replace(match: re.Match[str]) -> str:
            effects = [
                effect.strip()
                for effect in match.group(2).split(",")
                if effect.strip()
            ]
            if len(effects) <= 1:
                return f"{match.group(1)}{match.group(2)}{match.group(3)}"
            if effect_name and effect_name in effects:
                effects.remove(effect_name)
            else:
                effects = effects[1:]
            return f"{match.group(1)}{', '.join(effects)}{match.group(3)}"

        updated = re.sub(
            r"(effects\s*:\s*\[)([^\]]*)(\])",
            replace,
            scoped.text,
            count=1,
        )
        if updated == scoped.text:
            return source_code
        return source_code[:scoped.offset] + updated + source_code[scoped.end:]

    def _refine_i64_types(self, source_code: str, target_name: str = "") -> str:
        """Refine obvious bool locals or signed integer parameters."""
        local_refinement = re.sub(
            r"\blet\s+(is_[A-Za-z0-9_]*|has_[A-Za-z0-9_]*|flag)\s*=\s*(true|false)\b",
            lambda match: f"let {match.group(1)}: bool = {match.group(2)}",
            source_code,
            count=1,
        )
        if local_refinement != source_code:
            return local_refinement
        if not target_name:
            return source_code
        pattern = re.compile(rf"\b{re.escape(target_name)}\s*:\s*i64\b")
        return pattern.sub(f"{target_name}: i64 where {target_name} >= 0", source_code, count=1)

    def _insert_loop_invariant(
        self,
        source_code: str,
        invariant: str = "true",
        atom_name: str = "",
    ) -> str:
        """Insert a loop invariant immediately inside the first loop body."""
        selected = invariant.strip() or "true"
        scoped = self._scoped_region(source_code, atom_name)
        if re.search(rf"\binvariant\s*:\s*{re.escape(selected)}\s*;", scoped.text):
            return source_code
        loop_match = re.search(r"(?m)^([ \t]*)(while|for)\b[^\n{]*\{?[^\n]*(?:\n|$)", scoped.text)
        if loop_match is None:
            return source_code
        loop_line = loop_match.group(0)
        loop_indent = loop_match.group(1)
        invariant_indent = loop_indent + "    "
        if loop_line.endswith("\n"):
            insertion = f"{invariant_indent}invariant: {selected};\n"
        else:
            insertion = f"\n{invariant_indent}invariant: {selected};"
        abs_start = scoped.offset + loop_match.end()
        return source_code[:abs_start] + insertion + source_code[abs_start:]

    def _add_assertion(
        self,
        source_code: str,
        assertion: str = "true",
        atom_name: str = "",
    ) -> str:
        """Add an assertion at the start of the first body block."""
        selected = assertion.strip() or "true"
        scoped = self._scoped_region(source_code, atom_name)
        if re.search(rf"\bassert\s+{re.escape(selected)}\s*;", scoped.text):
            return source_code
        body_match = re.search(r"(body\s*:\s*\{)([^\n]*)", scoped.text)
        if body_match is None:
            return source_code
        line_start = scoped.text.rfind("\n", 0, body_match.start())
        current_indent = ""
        if line_start >= 0:
            line_text = scoped.text[line_start + 1:body_match.start()]
            indent_match = re.match(r"[ \t]*", line_text)
            if indent_match is not None:
                current_indent = indent_match.group(0)
        assertion_indent = current_indent + "    "
        insertion = f"\n{assertion_indent}assert {selected};"
        abs_start = scoped.offset + body_match.end(1)
        return source_code[:abs_start] + insertion + source_code[abs_start:]

    def _refactor_variable_names(
        self,
        source_code: str,
        rename_map: Mapping[str, str] | None = None,
        atom_name: str = "",
    ) -> str:
        """Rename one or more variables with conservative word-boundary edits."""
        scoped = self._scoped_region(source_code, atom_name)
        selected = dict(rename_map or {})
        if not selected:
            selected = self._infer_variable_rename(scoped.text)
        updated = scoped.text
        for old_name, new_name in selected.items():
            if old_name in {"result", "true", "false"}:
                continue
            if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", old_name):
                continue
            if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", new_name):
                continue
            updated = re.sub(rf"\b{re.escape(old_name)}\b", new_name, updated)
        if updated == scoped.text:
            return source_code
        return source_code[:scoped.offset] + updated + source_code[scoped.end:]

    def _infer_variable_rename(self, scoped_text: str) -> dict[str, str]:
        names = re.findall(r"\b(?:let\s+)?(tmp|val|flag|data|x)\b", scoped_text)
        if not names:
            return {}
        old_name = names[0]
        inferred = {
            "tmp": "tmp_value",
            "val": "value",
            "flag": "is_flag",
            "data": "payload_data",
            "x": "input_value",
        }
        return {old_name: inferred[old_name]}

    def _find_clause_span(
        self,
        source_code: str,
        clause_name: str,
        atom_name: str = "",
    ) -> tuple[int, int, str] | None:
        scoped = self._scoped_region(source_code, atom_name)
        match = re.search(rf"{clause_name}\s*:\s*(.+?)\s*;", scoped.text)
        if match is None:
            return None
        return scoped.offset + match.start(1), scoped.offset + match.end(1), match.group(1).strip()

    def _contains_constraint(self, expression: str, constraint: str) -> bool:
        normalized_expression = re.sub(r"\s+", "", expression)
        normalized_constraint = re.sub(r"\s+", "", constraint)
        return bool(normalized_constraint) and normalized_constraint in normalized_expression

    def _insert_clause_after_atom(
        self,
        source_code: str,
        clause_name: str,
        value: str,
        atom_name: str = "",
    ) -> str:
        decl_end = self._find_atom_declaration_end(source_code, atom_name)
        if decl_end is None:
            return source_code
        rest = source_code[decl_end:]
        indent_match = re.match(r"\n(\s+)", rest)
        indent = indent_match.group(1) if indent_match else "    "
        insertion = f"\n{indent}{clause_name}: {value};"
        return source_code[:decl_end] + insertion + source_code[decl_end:]

    def _find_atom_declaration_end(self, source_code: str, atom_name: str = "") -> int | None:
        return_type = r"(?:\s*->\s*[^\n{;]+)?"
        if atom_name:
            pattern = re.compile(rf"\batom\s+{re.escape(atom_name)}\s*\([^)]*\){return_type}")
        else:
            pattern = re.compile(rf"\batom\s+[A-Za-z_][A-Za-z0-9_]*\s*\([^)]*\){return_type}")
        match = pattern.search(source_code)
        if match is not None:
            return match.end()
        line_match = re.search(r"\batom\s+[A-Za-z_][A-Za-z0-9_]*[^\n]*", source_code)
        if line_match is None:
            return None
        return line_match.end()

    def _scoped_region(self, source_code: str, atom_name: str) -> "_ScopedRegion":
        if not atom_name:
            return _ScopedRegion(source_code, 0, len(source_code))
        decl_end = self._find_atom_declaration_end(source_code, atom_name)
        if decl_end is None:
            return _ScopedRegion(source_code, 0, len(source_code))
        rest = source_code[decl_end:]
        next_atom = re.search(r"\natom\s", rest)
        end = decl_end + next_atom.start() if next_atom is not None else len(source_code)
        return _ScopedRegion(source_code[decl_end:end], decl_end, end)


class _ScopedRegion:
    def __init__(self, text: str, offset: int, end: int) -> None:
        self.text = text
        self.offset = offset
        self.end = end
