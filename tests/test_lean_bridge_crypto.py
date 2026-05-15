"""Crypto-domain prompt and Lean fallback integration tests."""
from __future__ import annotations

import json
from pathlib import Path

from agent.lean_bridge import run_lean_bridge
from agent.prompts.spec_extraction import build_extraction_prompt


def _crypto_cert() -> dict:
    return {
        "version": "1.0",
        "timestamp": "2026-05-15T00:00:00Z",
        "mumei_version": "0.5.6",
        "z3_version": "4.12.2",
        "file": "std/crypto/rsa.mm",
        "atoms": [
            {
                "name": "rsa_identity_signature",
                "requires": "n > 0",
                "ensures": "mod(pow(signature, public_key), n) == mod(message, n)",
                "z3_check_result": "unknown",
                "status": "unknown",
                "content_hash": "h-rsa-identity",
                "proof_hash": "p-rsa-identity",
                "dependencies": [],
                "effects": [],
            },
            {
                "name": "field_add_bounds",
                "requires": "p > 1",
                "ensures": "mod(sum_ab, p) >= 0 && mod(sum_ab, p) < p",
                "z3_check_result": "unknown",
                "status": "unknown",
                "content_hash": "h-field-add",
                "proof_hash": "p-field-add",
                "dependencies": [],
                "effects": [],
            },
        ],
        "package_name": "std-crypto",
        "package_version": "0",
        "certificate_hash": "",
        "all_verified": False,
    }


def test_crypto_domain_hint_expands_contract_guidance() -> None:
    prompt = build_extraction_prompt(
        "RSA署名を公開鍵で検証し、有限体加算の境界を保証する",
        domain_hint="cryptography rsa signature",
    )

    assert "Cryptography domain conventions" in prompt
    assert "mod(pow(signature, public_key), n)" in prompt
    assert "mod(message, n)" in prompt
    assert "0 <= x < p" in prompt


def test_crypto_lean_bridge_returns_verified_crypto_certificate(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "mumei-lean"
    scripts_dir = repo / "scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "bridge.py").write_text(
        """
import argparse
import json

parser = argparse.ArgumentParser()
parser.add_argument("--cert")
parser.add_argument("--lean-cert-out")
parser.add_argument("--no-build", action="store_true")
args = parser.parse_args()

cert = json.loads(open(args.cert, encoding="utf-8").read())
ensures = "\\n".join(atom.get("ensures", "") for atom in cert["atoms"])
assert "pow(signature, public_key)" in ensures
assert "mod(pow(signature, public_key), n)" in ensures
assert "mod(message, n)" in ensures
assert "mod(sum_ab, p)" in ensures

out = {
    **cert,
    "lean_version": "4.15.0",
    "lean_cert_schema_version": "1.0-lean",
    "atoms": [
        {
            **atom,
            "z3_check_result": "lean_verified",
            "status": "verified",
        }
        for atom in cert["atoms"]
    ],
}
open(args.lean_cert_out, "w", encoding="utf-8").write(
    json.dumps(out, ensure_ascii=False)
)
""",
        encoding="utf-8",
    )
    cert_path = tmp_path / "crypto.proof-cert.json"
    cert_path.write_text(json.dumps(_crypto_cert()), encoding="utf-8")
    lean_cert = tmp_path / "crypto.lean-cert.json"

    result = run_lean_bridge(
        cert_path=cert_path,
        lean_cert_out=lean_cert,
        mumei_lean_repo=repo,
        no_build=False,
    )

    assert result["success"] is True, result["stderr"]
    assert result["lean_cert"] is not None
    statuses = {
        atom["name"]: atom["z3_check_result"]
        for atom in result["lean_cert"]["atoms"]
    }
    assert statuses["rsa_identity_signature"] == "lean_verified"
    assert statuses["field_add_bounds"] == "lean_verified"
