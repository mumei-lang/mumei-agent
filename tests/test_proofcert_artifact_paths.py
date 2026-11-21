"""Consumer-wiring tests for the canonical ``artifact_paths`` contract.

mumei-produced certificates and bundles record the artifact paths a harness
should collect or validate under the canonical ``artifact_paths`` key. These
tests pin the agent-side consumer surface: model accessors, nested-payload
collection, and existence validation — without new artifact keys or aliases.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

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


class TestPublishCertificateWiring:
    """publish() consumes the ``--proof-cert`` certificate file the CLI
    writes — not the ``verify --json`` report — and reports each declared
    artifact path as present or missing."""

    _CODE = "atom test_mod(x: i64) requires: x >= 0; body: x;"

    def _client_writing_cert(self, cert: dict) -> MagicMock:
        def _verify(path, report_dir=None, extra_args=None,
                    spec_code_mapping=None,
                    collect_decidable_metrics=False):
            if extra_args and "--output" in extra_args:
                out = Path(extra_args[extra_args.index("--output") + 1])
                out.write_text(json.dumps(cert), encoding="utf-8")
            return {
                "success": True, "report": {"status": "ok"},
                "stdout": "", "stderr": "",
            }

        client = MagicMock()
        client.verify.side_effect = _verify
        client.build_with_emit.return_value = {
            "success": True, "stdout": "ok", "stderr": "",
        }
        return client

    def _run_publish(self, tmp_path, client):
        from agent.publish import publish

        spec = {"name": "test_mod",
                "params": [{"name": "x", "type": "i64"}]}
        (tmp_path / "spec.json").write_text(json.dumps(spec))
        cfg = MagicMock()
        cfg.mumei_bin = "mumei"
        cfg.model = "m"
        cfg.max_retries = 1
        cfg.create_client.return_value = MagicMock()
        with patch("agent.publish.AgentConfig", return_value=cfg), \
             patch("agent.publish.create_mumei_client",
                   return_value=client):
            return publish(
                spec_path=str(tmp_path / "spec.json"),
                repo_dir=str(tmp_path),
                dry_run=True,
                pre_generated_code=self._CODE,
            )

    def test_cert_file_drives_artifact_paths_status(self, tmp_path):
        (tmp_path / "present.json").write_text("{}", encoding="utf-8")
        cert = _cert(artifact_paths=["present.json", "missing.json"])
        result = self._run_publish(
            tmp_path, self._client_writing_cert(cert),
        )
        assert result["success"] is True
        assert result["proof_certificate_file"] == "test_mod.proof.json"
        statuses = {
            entry["path"]: entry["exists"]
            for entry in result["artifact_paths_status"]
        }
        assert statuses == {"present.json": True, "missing.json": False}

    def test_no_cert_file_leaves_keys_absent(self, tmp_path):
        client = MagicMock()
        client.verify.return_value = {
            "success": True, "report": {}, "stdout": "", "stderr": "",
        }
        client.build_with_emit.return_value = {
            "success": True, "stdout": "ok", "stderr": "",
        }
        result = self._run_publish(tmp_path, client)
        assert result["success"] is True
        assert "proof_certificate_file" not in result
        assert "artifact_paths_status" not in result

    def test_cert_outside_repo_reports_absolute_path(self, tmp_path):
        # An absolute ``target_file`` places the generated module (and
        # its certificate) outside the repo: the result keeps the
        # absolute path instead of crashing in relative_to().
        repo = tmp_path / "repo"
        repo.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        spec = {
            "name": "test_mod",
            "params": [{"name": "x", "type": "i64"}],
            "target_file": str(outside / "test_mod.mm"),
        }
        (repo / "spec.json").write_text(json.dumps(spec))
        client = self._client_writing_cert(_cert())
        from agent.publish import publish

        cfg = MagicMock()
        cfg.mumei_bin = "mumei"
        cfg.model = "m"
        cfg.max_retries = 1
        cfg.create_client.return_value = MagicMock()
        with patch("agent.publish.AgentConfig", return_value=cfg), \
             patch("agent.publish.create_mumei_client",
                   return_value=client):
            result = publish(
                spec_path=str(repo / "spec.json"),
                repo_dir=str(repo),
                dry_run=True,
                pre_generated_code=self._CODE,
            )
        assert result["success"] is True
        assert result["proof_certificate_file"] == str(
            outside / "test_mod.proof.json"
        )

    def test_stale_cert_from_prior_run_is_not_consumed(self, tmp_path):
        # A certificate left by an earlier run must not be reported as
        # this run's — unlink happens before verify, so a client that
        # writes no cert leaves the keys absent even with a file
        # already on disk.
        (tmp_path / "test_mod.proof.json").write_text(
            json.dumps(_cert(artifact_paths=["stale.json"]))
        )
        client = MagicMock()
        client.verify.return_value = {
            "success": True, "report": {}, "stdout": "", "stderr": "",
        }
        client.build_with_emit.return_value = {
            "success": True, "stdout": "ok", "stderr": "",
        }
        result = self._run_publish(tmp_path, client)
        assert result["success"] is True
        assert "artifact_paths_status" not in result
        # ...and the previous certificate is restored, not lost, when
        # this run produced none.
        assert json.loads(
            (tmp_path / "test_mod.proof.json").read_text()
        )["artifact_paths"] == ["stale.json"]

    def test_mcp_verdict_governs_even_when_cli_cert_passes(
        self, tmp_path,
    ):
        # The MCP verdict path must decide publishability: when the
        # MCP verify fails, a succeeding CLI-only cert pass cannot
        # publish.  spec'd MagicMock satisfies the isinstance check.
        from agent.mcp_client import MumeiMCPClient

        calls = []

        def _verify(path, report_dir=None, extra_args=None,
                    spec_code_mapping=None,
                    collect_decidable_metrics=False):
            calls.append(bool(extra_args))
            if extra_args:
                out = Path(extra_args[extra_args.index("--output") + 1])
                out.write_text(json.dumps(_cert()), encoding="utf-8")
                return {
                    "success": True, "report": {}, "stdout": "",
                    "stderr": "",
                }
            return {
                "success": False, "report": None,
                "stdout": "", "stderr": "mcp verify failed",
            }

        client = MagicMock(spec=MumeiMCPClient)
        client.mode = "in-process"
        client.verify.side_effect = _verify
        result = self._run_publish(tmp_path, client)
        assert result["success"] is False
        assert "verify_error" in result
        assert calls == [False, True]  # MCP verdict, then CLI cert pass
        assert "artifact_paths_status" not in result
