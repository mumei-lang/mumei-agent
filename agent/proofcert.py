"""Typed accessors for Mumei proof certificates.

This module mirrors the canonical proof-certificate schema copied from the
``mumei`` repository and keeps the certificate-level vocabularies in one place.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class Z3CheckResult(str, Enum):
    UNSAT = "unsat"
    SAT = "sat"
    UNKNOWN = "unknown"
    SKIPPED = "skipped"
    LEAN_VERIFIED = "lean_verified"


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    FAILED = "failed"
    SKIPPED = "skipped"
    TRUSTED = "trusted"
    ESCALATION_CANDIDATE = "escalation_candidate"


def _maybe_enum(value: object, enum_cls: type[Enum]) -> object:
    if not isinstance(value, str):
        return value
    try:
        return enum_cls(value)
    except ValueError:
        return value


def _mapping(value: object) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, Mapping):
        return dict(value)
    return None


def _string(value: object) -> str | None:
    return value if isinstance(value, str) else None


@dataclass(slots=True)
class AtomCertificate:
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AtomCertificate":
        return cls(raw=data if isinstance(data, dict) else dict(data))

    @classmethod
    def from_path(cls, path: str | Path) -> "AtomCertificate":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise TypeError("atom certificate must be a mapping")
        return cls.from_dict(payload)

    @property
    def name(self) -> str | None:
        return _string(self.raw.get("name"))

    @property
    def z3_check_result(self) -> Z3CheckResult | str | None:
        return _maybe_enum(self.raw.get("z3_check_result"), Z3CheckResult)

    @property
    def status(self) -> VerificationStatus | str | None:
        return _maybe_enum(self.raw.get("status"), VerificationStatus)

    @property
    def body_expr(self) -> str | None:
        return _string(self.raw.get("body_expr"))

    @property
    def requires(self) -> str | None:
        return _string(self.raw.get("requires"))

    @property
    def ensures(self) -> str | None:
        return _string(self.raw.get("ensures"))

    @property
    def content_hash(self) -> str | None:
        return _string(self.raw.get("content_hash"))

    @property
    def proof_hash(self) -> str | None:
        return _string(self.raw.get("proof_hash"))

    @property
    def z3_result_class(self) -> str | None:
        return _string(self.raw.get("z3_result_class"))

    @property
    def escalation_reason(self) -> str | None:
        return _string(self.raw.get("escalation_reason"))

    @property
    def translator_version(self) -> str | None:
        return _string(self.raw.get("translator_version"))

    @property
    def bridge_lemma_hash(self) -> str | None:
        return _string(self.raw.get("bridge_lemma_hash"))

    @property
    def lean_metadata(self) -> dict[str, Any] | None:
        return _mapping(self.raw.get("lean_metadata"))

    @property
    def lean_result_metadata(self) -> dict[str, Any] | None:
        return _mapping(self.raw.get("lean_result_metadata"))


@dataclass(slots=True)
class ProofCertificate:
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProofCertificate":
        return cls(raw=data if isinstance(data, dict) else dict(data))

    @classmethod
    def from_path(cls, path: str | Path) -> "ProofCertificate":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise TypeError("proof certificate must be a mapping")
        return cls.from_dict(payload)

    @property
    def file(self) -> str | None:
        return _string(self.raw.get("file"))

    @property
    def version(self) -> str | None:
        return _string(self.raw.get("version"))

    @property
    def mumei_version(self) -> str | None:
        return _string(self.raw.get("mumei_version"))

    @property
    def z3_version(self) -> str | None:
        return _string(self.raw.get("z3_version"))

    @property
    def certificate_hash(self) -> str | None:
        return _string(self.raw.get("certificate_hash"))

    @property
    def all_verified(self) -> bool | None:
        value = self.raw.get("all_verified")
        return value if isinstance(value, bool) else None

    @property
    def atoms(self) -> list[AtomCertificate]:
        atoms = self.raw.get("atoms")
        if not isinstance(atoms, list):
            return []
        return [
            AtomCertificate.from_dict(atom)
            for atom in atoms
            if isinstance(atom, Mapping)
        ]

    @property
    def candidates(self) -> list[AtomCertificate]:
        candidates = self.raw.get("candidates")
        if not isinstance(candidates, list):
            return []
        return [
            AtomCertificate.from_dict(candidate)
            for candidate in candidates
            if isinstance(candidate, Mapping)
        ]

    @property
    def modules(self) -> dict[str, Any] | None:
        return _mapping(self.raw.get("modules"))

    def iter_atoms(
        self,
        include_candidates: bool = True,
    ) -> Iterator[AtomCertificate]:
        return iter_atoms(self, include_candidates=include_candidates)


def iter_atoms(
    cert_or_payload: object,
    *,
    include_candidates: bool = True,
) -> Iterator[AtomCertificate]:
    """Yield every atom embedded in a certificate-like payload."""

    visited: set[int] = set()

    def _consume(payload: object) -> Iterator[AtomCertificate]:
        if isinstance(payload, AtomCertificate):
            yield payload
            return
        if isinstance(payload, ProofCertificate):
            payload = payload.raw
        if not isinstance(payload, Mapping):
            return
        payload_id = id(payload)
        if payload_id in visited:
            return
        visited.add(payload_id)

        for item in payload.get("atoms") or []:
            if isinstance(item, Mapping):
                yield AtomCertificate.from_dict(item)
        if include_candidates:
            for item in payload.get("candidates") or []:
                if isinstance(item, Mapping):
                    yield AtomCertificate.from_dict(item)

        modules = payload.get("modules")
        if isinstance(modules, Mapping):
            for module_cert in modules.values():
                yield from _consume(module_cert)

        for key in ("certificate", "report", "proof_certificate"):
            nested = payload.get(key)
            if isinstance(nested, Mapping):
                yield from _consume(nested)

    yield from _consume(cert_or_payload)


__all__ = [
    "AtomCertificate",
    "ProofCertificate",
    "VerificationStatus",
    "Z3CheckResult",
    "iter_atoms",
]
