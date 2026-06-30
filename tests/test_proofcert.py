from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from agent.proofcert import (
    ProofCertificate,
    VerificationStatus,
    Z3CheckResult,
    iter_atoms,
)
from tests.test_lean_bridge_e2e import ABS_SATURATING_BODY, LEAN_PROOF_ATOM


def _schema_path() -> Path:
    return Path(__file__).resolve().parents[1] / "schema" / "proof-cert.schema.json"


def _schema() -> dict:
    return json.loads(_schema_path().read_text(encoding="utf-8"))


def _representative_certificate() -> dict:
    cert = {
        "version": "p0-b-test",
        "timestamp": "2024-01-01T00:00:00Z",
        "z3_version": "4.12.2",
        "file": "std/math/abs.mm",
        "mumei_version": "test-fixture",
        "all_verified": True,
        "atoms": [
            {
                "name": LEAN_PROOF_ATOM,
                "z3_check_result": Z3CheckResult.LEAN_VERIFIED.value,
                "status": VerificationStatus.VERIFIED.value,
                "content_hash": "fixture-abs-saturating",
                "requires": "true",
                "ensures": "result >= 0",
                "body_expr": ABS_SATURATING_BODY,
                "z3_result_class": "unknown",
            }
        ],
    }
    return cert


def test_enum_values_match_vendored_schema() -> None:
    schema = _schema()

    assert [member.value for member in Z3CheckResult] == schema["$defs"][
        "z3CheckResult"
    ]["enum"]
    assert [member.value for member in VerificationStatus] == schema["$defs"][
        "verificationStatus"
    ]["enum"]


def test_from_dict_round_trips_raw() -> None:
    payload = _representative_certificate()
    cert = ProofCertificate.from_dict(payload)

    assert cert.raw == payload
    assert cert.file == "std/math/abs.mm"
    assert cert.atoms[0].name == LEAN_PROOF_ATOM
    assert cert.atoms[0].z3_check_result == Z3CheckResult.LEAN_VERIFIED
    assert cert.atoms[0].status == VerificationStatus.VERIFIED


def test_iter_atoms_flattens_atoms_candidates_and_modules() -> None:
    payload = {
        "atoms": [{"name": "root_atom", "z3_check_result": "unknown"}],
        "candidates": [{"name": "root_candidate", "z3_check_result": "unknown"}],
        "modules": {
            "std/foo.mm": {
                "atoms": [{"name": "module_atom", "z3_check_result": "unknown"}],
                "modules": {
                    "std/bar.mm": {
                        "candidates": [
                            {"name": "nested_candidate", "z3_check_result": "unknown"}
                        ]
                    }
                },
            }
        },
    }

    names = [atom.name for atom in iter_atoms(payload)]
    atom_only_names = [atom.name for atom in iter_atoms(payload, include_candidates=False)]
    cert = ProofCertificate.from_dict(payload)
    cert_names = [atom.name for atom in cert.iter_atoms()]
    cert_atom_only_names = [
        atom.name for atom in cert.iter_atoms(include_candidates=False)
    ]

    assert names == [
        "root_atom",
        "root_candidate",
        "module_atom",
        "nested_candidate",
    ]
    assert atom_only_names == ["root_atom", "module_atom"]
    assert cert_names == names
    assert cert_atom_only_names == atom_only_names


def test_representative_certificate_validates_against_schema() -> None:
    schema = _schema()
    cert = _representative_certificate()

    Draft202012Validator(schema).validate(cert)

    top_level_keys = set(cert)
    schema_top_level_keys = set(schema.get("properties", {}))
    assert top_level_keys <= schema_top_level_keys

    atom_keys = set(cert["atoms"][0])
    schema_atom_keys = set(schema["$defs"]["atomCertificate"]["properties"])
    assert atom_keys <= schema_atom_keys
