"""Encode Mumei code and verifier state into latent feature vectors."""
from __future__ import annotations

import re
from typing import Any

import numpy as np


EFFECT_FEATURE_TYPES = (
    "read",
    "write",
    "file",
    "http",
    "settlement",
    "temporal",
)


class LatentEncoder:
    """Mumei-specific NLAE-inspired latent encoder.

    The current implementation is intentionally lightweight and deterministic:
    it extracts structural, contract, and verifier-report features without
    depending on an external neural checkpoint.
    """

    def encode_to_latent(
        self,
        source_code: str,
        verification_report: dict[str, Any],
    ) -> np.ndarray:
        """Return a latent feature vector for source plus verification state."""
        syntax_features = self._extract_syntax_features(source_code)
        semantic_features = self._extract_semantic_features(source_code)
        effect_features = self._extract_effect_features(source_code)
        dependency_features = self._extract_dependency_features(source_code)
        contract_features = self._extract_contract_complexity_features(source_code)
        scope_features = self._extract_scope_features(source_code)
        verification_features = self._extract_verification_features(
            verification_report,
        )
        return self._combine_features(
            syntax_features,
            semantic_features,
            effect_features,
            dependency_features,
            contract_features,
            scope_features,
            verification_features,
        )

    def _extract_syntax_features(self, source_code: str) -> np.ndarray:
        """Extract variable, type, control-flow, and size features."""
        var_names = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\s*:", source_code)
        types = re.findall(r":\s*(i64|bool|string|\w+)", source_code)
        control_flow = re.findall(r"\b(if|while|for|match)\b", source_code)
        atoms = re.findall(r"\batom\s+[A-Za-z_][A-Za-z0-9_]*", source_code)
        return np.array(
            [
                len(var_names),
                len(types),
                len(control_flow),
                len(source_code),
                len(atoms),
            ],
            dtype=np.float32,
        )

    def _extract_semantic_features(self, source_code: str) -> np.ndarray:
        """Extract requires/ensures/effects feature counts."""
        requires_matches = re.findall(r"requires\s*:\s*([^;]+);", source_code)
        ensures_matches = re.findall(r"ensures\s*:\s*([^;]+);", source_code)
        effects_matches = re.findall(r"effects\s*:\s*\[([^\]]*)\]", source_code)
        return np.array(
            [
                len(requires_matches),
                len(ensures_matches),
                sum(len(m) for m in requires_matches),
                sum(len(m) for m in ensures_matches),
                len(effects_matches),
            ],
            dtype=np.float32,
        )

    def _extract_effect_features(self, source_code: str) -> np.ndarray:
        """Extract effect category counts and declaration complexity."""
        effects_matches = re.findall(r"effects\s*:\s*\[([^\]]*)\]", source_code)
        effect_types: list[str] = []
        for match in effects_matches:
            effect_types.extend(
                effect.strip()
                for effect in match.split(",")
                if effect.strip()
            )
        category_counts = self._encode_effect_types(effect_types)
        return np.concatenate(
            [
                category_counts,
                np.array(
                    [
                        len(effect_types),
                        len(set(effect_types)),
                    ],
                    dtype=np.float32,
                ),
            ],
        )

    def _encode_effect_types(self, effect_types: list[str]) -> np.ndarray:
        """One-hot-like effect category encoding."""
        lowered = [effect.lower() for effect in effect_types]
        counts = []
        for category in EFFECT_FEATURE_TYPES:
            counts.append(sum(1 for effect in lowered if category in effect))
        return np.array(counts, dtype=np.float32)

    def _extract_dependency_features(self, source_code: str) -> np.ndarray:
        """Extract atom call-graph depth features."""
        atom_names = re.findall(r"\batom\s+([A-Za-z_][A-Za-z0-9_]*)", source_code)
        atom_blocks = re.findall(
            r"\batom\s+([A-Za-z_][A-Za-z0-9_]*)[\s\S]*?body\s*:\s*\{([\s\S]*?)\}\s*;",
            source_code,
        )
        graph: dict[str, set[str]] = {name: set() for name in atom_names}
        for atom_name, body in atom_blocks:
            calls = re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", body)
            graph.setdefault(atom_name, set()).update(
                call for call in calls if call in graph and call != atom_name
            )

        def depth(name: str, seen: set[str]) -> int:
            children = graph.get(name, set()) - seen
            if not children:
                return 0
            return 1 + max(depth(child, seen | {child}) for child in children)

        edge_count = sum(len(children) for children in graph.values())
        max_depth = max((depth(name, {name}) for name in graph), default=0)
        recursive_edges = sum(
            1
            for name, children in graph.items()
            if name in children
        )
        return np.array([edge_count, max_depth, recursive_edges], dtype=np.float32)

    def _extract_contract_complexity_features(self, source_code: str) -> np.ndarray:
        """Extract nesting, connective, and quantifier counts from contracts."""
        contract_matches = re.findall(
            r"(?:requires|ensures)\s*:\s*([^;]+);",
            source_code,
        )
        contract_text = " && ".join(contract_matches)
        max_depth = 0
        current_depth = 0
        for char in contract_text:
            if char == "(":
                current_depth += 1
                max_depth = max(max_depth, current_depth)
            elif char == ")":
                current_depth = max(0, current_depth - 1)
        return np.array(
            [
                max_depth,
                contract_text.count("&&"),
                contract_text.count("||"),
                len(re.findall(r"\b(forall|exists)\b", contract_text)),
                len(re.findall(r"(<=|>=|==|!=|<|>)", contract_text)),
                len(contract_text),
            ],
            dtype=np.float32,
        )

    def _extract_scope_features(self, source_code: str) -> np.ndarray:
        """Extract parameter/local variable scope features."""
        atom_headers = re.findall(
            r"\batom\s+[A-Za-z_][A-Za-z0-9_]*\s*\(([^)]*)\)",
            source_code,
        )
        params: list[str] = []
        for header in atom_headers:
            params.extend(
                match.group(1)
                for match in re.finditer(
                    r"\b([A-Za-z_][A-Za-z0-9_]*)\s*:",
                    header,
                )
            )
        locals_ = re.findall(r"\blet\s+([A-Za-z_][A-Za-z0-9_]*)\b", source_code)
        scoped = params + locals_
        shadowed = len(scoped) - len(set(scoped))
        return np.array(
            [
                len(params),
                len(locals_),
                len(set(scoped)),
                shadowed,
            ],
            dtype=np.float32,
        )

    def _extract_verification_features(
        self,
        verification_report: dict[str, Any],
    ) -> np.ndarray:
        """Extract verifier failure and counterexample features."""
        violation_type = str(
            verification_report.get("violation_type")
            or verification_report.get("failure_type")
            or "",
        )
        counterexample = verification_report.get("counterexample", {})
        if not isinstance(counterexample, dict):
            counterexample = {}
        unsat_core = verification_report.get("structured_unsat_core", [])
        if not isinstance(unsat_core, list):
            unsat_core = []
        return np.array(
            [
                len(violation_type),
                len(counterexample),
                1.0 if violation_type else 0.0,
                len(unsat_core),
            ],
            dtype=np.float32,
        )

    def _combine_features(
        self,
        syntax: np.ndarray,
        semantic: np.ndarray,
        effects: np.ndarray,
        dependency: np.ndarray,
        contract: np.ndarray,
        scope: np.ndarray,
        verification: np.ndarray,
    ) -> np.ndarray:
        """Combine extracted feature groups into one vector."""
        return np.concatenate(
            [
                syntax,
                semantic,
                effects,
                dependency,
                contract,
                scope,
                verification,
            ],
        )
