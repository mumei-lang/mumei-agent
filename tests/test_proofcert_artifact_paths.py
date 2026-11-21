"""Consumer-wiring tests for the canonical ``artifact_paths`` contract.

mumei-produced certificates and bundles record the artifact paths a harness
should collect or validate under the canonical ``artifact_paths`` key. These
tests pin the agent-side consumer surface: model accessors, nested-payload
collection, and existence validation — without new artifact keys or aliases.
"""
from __future__ import annotations

from pathlib import Path

from agent.proofcert import (
    ProofCertificate,
    artifact_paths_of,
    validate_artifact_paths,
)


def _cert(**overrides) -> dict:
    cert = {
        "file": "std/math.mm",
        "version": "1",
        "atoms": [{"name": "add", "z3_check_result": "unsat"}],
    }
    cert.update(overrides)
    return cert


class TestProofCertificateHarnessMetadata:
    def test_p5a_fields_exposed_when_present(self) -> None:
        cert = ProofCertificate.from_dict(
            _cert(
                harness_contract="docs/AGENT_HARNESS_SPEC.md",
                intent_fidelity={"spec_traceability_score": 0.9},
                artifact_paths=["std/certs/math.json", "dist/bundle.json"],
                budget_policy_fingerprint="fp-123",
                lean_provenance={"bridge": "mumei-lean"},
            )
        )
        assert cert.harness_contract == "docs/AGENT_HARNESS_SPEC.md"
        assert cert.intent_fidelity == {"spec_traceability_score": 0.9}
        assert cert.artifact_paths == ["std/certs/math.json", "dist/bundle.json"]
        assert cert.budget_policy_fingerprint == "fp-123"
        assert cert.lean_provenance == {"bridge": "mumei-lean"}

    def test_absent_fields_default(self) -> None:
        cert = ProofCertificate.from_dict(_cert())
        assert cert.harness_contract is None
        assert cert.intent_fidelity is None
        assert cert.artifact_paths == []
        assert cert.budget_policy_fingerprint is None
        assert cert.lean_provenance is None


class TestArtifactPathsOf:
    def test_collects_from_nested_certificate_payloads(self) -> None:
        payload = {
            "artifact_paths": ["bundle.json"],
            "modules": {
                "math": {"artifact_paths": ["std/certs/math.json"]},
                "io": {},
            },
            "certificate": {"artifact_paths": ["std/certs/math.json", "extra.json"]},
        }
        assert artifact_paths_of(payload) == [
            "bundle.json",
            "std/certs/math.json",
            "extra.json",
        ]

    def test_accepts_proof_certificate_and_ignores_non_strings(self) -> None:
        cert = ProofCertificate.from_dict(
            _cert(artifact_paths=["a.json", 7, None, "b.json"])
        )
        assert artifact_paths_of(cert) == ["a.json", "b.json"]
        assert artifact_paths_of("not-a-mapping") == []
        assert artifact_paths_of(None) == []


class TestValidateArtifactPaths:
    def test_reports_existence_per_declared_path(self, tmp_path: Path) -> None:
        (tmp_path / "present.json").write_text("{}")
        rows = validate_artifact_paths(
            ["present.json", "missing.json"], base_dir=tmp_path
        )
        assert rows == [
            {
                "path": "present.json",
                "exists": True,
                "resolved": str(tmp_path / "present.json"),
            },
            {
                "path": "missing.json",
                "exists": False,
                "resolved": str(tmp_path / "missing.json"),
            },
        ]

    def test_absolute_paths_bypass_base_dir(self, tmp_path: Path) -> None:
        target = tmp_path / "abs.json"
        target.write_text("{}")
        rows = validate_artifact_paths([str(target)], base_dir=tmp_path / "other")
        assert rows[0]["exists"] is True
        assert rows[0]["resolved"] == str(target)

    def test_non_list_and_non_string_entries_ignored(self) -> None:
        assert validate_artifact_paths("path.json") == []
        assert validate_artifact_paths([1, "x"]) == [
            {
                "path": "x",
                "exists": False,
                "resolved": str(Path.cwd() / "x"),
            }
        ]


class TestPublishResultSummaryWiring:
    def test_jsonify_surfaces_cert_metadata(self) -> None:
        from agent.proliferate_report import _jsonify_result

        cert = _cert(
            all_verified=True,
            artifact_paths=["std/certs/math.json"],
            harness_contract="docs/AGENT_HARNESS_SPEC.md",
            budget_policy_fingerprint="fp-9",
        )
        out = _jsonify_result(
            {
                "publish_result": {
                    "success": True,
                    "proof_certificate": cert,
                },
                "upgraded_cert": {**cert, "lean_provenance": {"bridge": "x"}},
            }
        )
        summary = out["publish_result"]["proof_certificate_summary"]
        assert summary["artifact_paths"] == ["std/certs/math.json"]
        assert summary["harness_contract"] == "docs/AGENT_HARNESS_SPEC.md"
        assert summary["budget_policy_fingerprint"] == "fp-9"
        upgraded = out["upgraded_cert_summary"]
        assert upgraded["artifact_paths"] == ["std/certs/math.json"]
        assert upgraded["lean_provenance"] == {"bridge": "x"}

    def test_jsonify_keeps_artifact_paths_status(self) -> None:
        from agent.proliferate_report import _jsonify_result

        out = _jsonify_result(
            {
                "publish_result": {
                    "success": True,
                    "proof_certificate_file": "gen.proof.json",
                    "artifact_paths_status": [
                        {"path": "a.json", "exists": True, "resolved": "a.json"}
                    ],
                }
            }
        )
        short = out["publish_result"]
        assert short["proof_certificate_file"] == "gen.proof.json"
        assert short["artifact_paths_status"] == [
            {"path": "a.json", "exists": True, "resolved": "a.json"}
        ]

    def test_jsonify_omits_absent_metadata(self) -> None:
        from agent.proliferate_report import _jsonify_result

        out = _jsonify_result(
            {
                "publish_result": {
                    "success": True,
                    "proof_certificate": _cert(),
                }
            }
        )
        summary = out["publish_result"]["proof_certificate_summary"]
        assert "artifact_paths" not in summary
        assert "harness_contract" not in summary
