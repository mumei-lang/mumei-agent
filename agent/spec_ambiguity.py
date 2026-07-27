"""Conservative missing-requirement vs underspecified-intent reporting.

The natural-language extraction pipeline turns prose into contract clauses. When
the prose does not pin a clause down there are two very different situations,
and the pipeline must not silently pick one:

``missing_requirement``
    The extracted contract clause is trivial (absent, empty, or ``true``) *and*
    the prose never mentions the subject at all. Nothing was stated, so nothing
    can be inferred: the requirement has to come from a human.

``underspecified_intent``
    The prose does talk about the subject, but not precisely enough to become a
    clause — a vague adjective, a non-actionable quantifier, a conditional with
    no else case, or a clause that stayed trivial despite the subject being
    described. The intent exists; its formalisation does not.

Both are reported through the existing fixed audit keys
(``cross_validation_gaps`` / ``next_steps`` / ``verification_status``): no new
verdict classification or alias is introduced. Classification never rewrites the
spec — an ambiguous requirement is reported, never completed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from agent.ambiguity_detector import AmbiguityDetector
from agent.config import AgentConfig

AmbiguityClass = Literal["missing_requirement", "underspecified_intent"]

AMBIGUITY_CLASSES: tuple[AmbiguityClass, ...] = (
    "missing_requirement",
    "underspecified_intent",
)

# Clause values that carry no proof obligation, so they cannot stand in for a
# requirement the prose failed to state.
_TRIVIAL_CLAUSES = frozenset({"", "true", "1", "none", "n/a"})

_WORD_RE = re.compile(r"[0-9a-zA-Z]+")
# Identifier fragments that say nothing about the subject of a requirement.
_STOP_WORDS = frozenset({"get", "set", "is", "to", "of", "the", "a", "an", "do", "run"})


@dataclass(frozen=True)
class SpecAmbiguity:
    """One conservatively classified ambiguity in an extracted spec."""

    classification: AmbiguityClass
    subject: str
    evidence: str
    clarification: str
    # Whether the ambiguity leaves the verified contract itself without
    # content; prose-only vagueness does not.
    affects_contract: bool = False

    def as_gap(self) -> str:
        """Render as a ``cross_validation_gaps`` entry."""
        return (
            f"spec ambiguity ({self.classification}): {self.subject} — "
            f"{self.evidence} {self.clarification}"
        )


def _subject_words(atom_name: str) -> list[str]:
    words = [
        word.lower()
        for word in _WORD_RE.findall(atom_name.replace("_", " "))
        if len(word) > 2
    ]
    return [word for word in words if word not in _STOP_WORDS]


def _prose_mentions(natural_language: str, atom_name: str) -> bool:
    """Whether the prose talks about ``atom_name`` at all.

    Deliberately generous: any subject word of the atom appearing in the prose
    counts as "mentioned", so an unmentioned subject is strong evidence that the
    requirement is genuinely missing rather than merely vague.
    """
    text = natural_language.lower()
    if atom_name.lower() in text:
        return True
    return any(word in text for word in _subject_words(atom_name))


def _atoms_of(spec: object) -> list[dict[str, Any]]:
    if not isinstance(spec, dict):
        return []
    atoms = spec.get("atoms")
    if not isinstance(atoms, list):
        return []
    return [atom for atom in atoms if isinstance(atom, dict)]


def _is_trivial(clause: object) -> bool:
    if clause is None:
        return True
    if not isinstance(clause, str):
        return False
    return clause.strip().lower() in _TRIVIAL_CLAUSES


def classify_contract_gaps(
    natural_language: str,
    spec: object,
) -> list[SpecAmbiguity]:
    """Classify trivial contract clauses in ``spec`` against the prose."""
    ambiguities: list[SpecAmbiguity] = []
    for atom in _atoms_of(spec):
        name = str(atom.get("name", "")).strip()
        if not name:
            continue
        mentioned = _prose_mentions(natural_language, name)
        for label in ("requires", "ensures"):
            if not _is_trivial(atom.get(label)):
                continue
            subject = f"{name}.{label}"
            if mentioned:
                ambiguities.append(
                    SpecAmbiguity(
                        classification="underspecified_intent",
                        subject=subject,
                        evidence=(
                            "the requirement text describes this atom but the "
                            f"extracted {label} clause stayed trivial."
                        ),
                        clarification=(
                            f"State the {label} condition explicitly; it was not "
                            "inferred."
                        ),
                        affects_contract=True,
                    )
                )
            else:
                ambiguities.append(
                    SpecAmbiguity(
                        classification="missing_requirement",
                        subject=subject,
                        evidence=(
                            "no requirement text mentions this atom and the "
                            f"extracted {label} clause is trivial."
                        ),
                        clarification=(
                            f"Add a requirement covering {name}; none was stated."
                        ),
                        affects_contract=True,
                    )
                )
    return ambiguities


def classify_prose_ambiguity(
    natural_language: str,
    config: AgentConfig | None = None,
) -> list[SpecAmbiguity]:
    """Classify vague prose as underspecified intent (never as missing)."""
    if not natural_language.strip():
        return []
    detector = AmbiguityDetector(config or AgentConfig())
    result = detector.detect_ambiguity(natural_language, use_llm=False)
    ambiguities: list[SpecAmbiguity] = []
    for finding in result.findings:
        clarifications = detector.suggest_disambiguation(finding)
        ambiguities.append(
            SpecAmbiguity(
                classification="underspecified_intent",
                subject=f"{finding.ambiguity_type} at {finding.location}",
                evidence=f"'{finding.ambiguous_text}' is stated but not pinned down.",
                clarification=clarifications[0] if clarifications else "",
            )
        )
    return ambiguities


def classify_spec_ambiguity(
    natural_language: str,
    spec: object,
    config: AgentConfig | None = None,
) -> list[SpecAmbiguity]:
    """Report every ambiguity in an extraction, conservatively classified.

    Contract-level gaps come first because they are the ones that leave the
    verified contract without content.
    """
    return [
        *classify_contract_gaps(natural_language, spec),
        *classify_prose_ambiguity(natural_language, config),
    ]
