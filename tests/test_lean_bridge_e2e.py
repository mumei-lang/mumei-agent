"""Live E2E tests for the mumei-agent → mumei-lean fallback path."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent import lean_bridge
from agent import proliferate as proliferate_mod

pytestmark = pytest.mark.integration


LEAN_PROOF_ATOM = "abs_saturating"
ABS_SATURATING_BODY = (
    "if x == (0 - 9223372036854775807 - 1) then 9223372036854775807 "
    "else if x >= 0 then x else 0 - x"
)


@pytest.fixture()
def mumei_lean_repo() -> Path:
    repo = Path(
        os.environ.get("MUMEI_LEAN_REPO", "/home/ubuntu/repos/mumei-lean")
    ).resolve()
    if not (repo / "scripts" / "bridge.py").exists():
        pytest.skip(f"mumei-lean bridge.py not found at {repo}")
    if shutil.which("lake") is None:
        elan_bin = Path.home() / ".elan" / "bin"
        if shutil.which("lake", path=f"{elan_bin}:{os.environ.get('PATH', '')}"):
            os.environ["PATH"] = f"{elan_bin}:{os.environ.get('PATH', '')}"
    if shutil.which("lake") is None:
        pytest.skip("lake not on PATH; skipping live Lean fallback E2E")
    return repo


@pytest.fixture()
def std_abs_unknown_cert() -> dict:
    return {
        "file": "std/math/abs.mm",
        "mumei_version": "test-fixture",
        "all_verified": False,
        "atoms": [
            {
                "name": LEAN_PROOF_ATOM,
                "z3_check_result": "unknown",
                "status": "unknown",
                "requires": "true",
                "ensures": "result >= 0",
                "body_expr": ABS_SATURATING_BODY,
                "z3_result_class": "unknown",
                "escalation_reason": "timeout",
                "content_hash": "fixture-abs-saturating",
            }
        ],
    }


@pytest.fixture()
def std_multi_unknown_cert() -> dict:
    return {
        "file": "std/math/abs.mm",
        "mumei_version": "test-fixture",
        "all_verified": False,
        "atoms": [
            {
                "name": "abs_saturating",
                "z3_check_result": "unknown",
                "status": "unknown",
                "requires": "true",
                "ensures": "result >= 0",
                "body_expr": ABS_SATURATING_BODY,
                "z3_result_class": "unknown",
                "escalation_reason": "timeout",
                "content_hash": "fixture-abs-saturating",
            },
            {
                "name": "list_length",
                "z3_check_result": "unknown",
                "status": "unknown",
                "requires": "listTag >= 0",
                "ensures": "result >= 0",
                "body_expr": "listTag",
                "z3_result_class": "unknown",
                "escalation_reason": "timeout",
                "content_hash": "fixture-list-length",
            },
        ],
    }


def test_lean_fallback_upgrades_unknown_to_lean_verified(
    tmp_path: Path,
    mumei_lean_repo: Path,
    std_abs_unknown_cert: dict,
) -> None:
    cert_path = tmp_path / "std-abs.proof-cert.json"
    lean_cert_out = tmp_path / "std-abs.lean-cert.json"
    cert_path.write_text(json.dumps(std_abs_unknown_cert), encoding="utf-8")

    bridge_result = lean_bridge.run_lean_bridge(
        cert_path=cert_path,
        lean_cert_out=lean_cert_out,
        mumei_lean_repo=mumei_lean_repo,
    )

    assert bridge_result["success"] is True, bridge_result.get("stderr", "")
    assert isinstance(bridge_result["lean_cert"], dict)
    lean_verified = [
        atom
        for atom in bridge_result["lean_cert"]["atoms"]
        if atom["z3_check_result"] == "lean_verified"
    ]
    assert len(lean_verified) > 0
    upgraded = lean_bridge.merge_lean_cert_into_proof_cert(
        std_abs_unknown_cert,
        bridge_result["lean_cert"],
    )
    atom = next(a for a in upgraded["atoms"] if a["name"] == LEAN_PROOF_ATOM)
    assert atom["z3_check_result"] == "lean_verified"
    assert atom["status"] == "verified"
    assert atom["lean_metadata"]["lean_theorem_name"] == (
        "Generated.Std.Math.Abs.abs_saturating_correct"
    )
    assert atom["lean_metadata"]["known_witness_used"] is False
    assert upgraded["all_verified"] is True


def test_lean_bridge_accepts_escalation_bundle_fixture(
    tmp_path: Path,
    mumei_lean_repo: Path,
) -> None:
    bundle_path = (
        mumei_lean_repo
        / "tests"
        / "fixtures"
        / "abs_saturating.escalation-bundle.json"
    )
    if not bundle_path.exists():
        pytest.skip(f"escalation-bundle fixture not found at {bundle_path}")

    lean_cert_out = tmp_path / "abs_saturating.lean-cert.json"
    bridge_result = lean_bridge.run_lean_bridge(
        cert_path=None,
        lean_cert_out=lean_cert_out,
        mumei_lean_repo=mumei_lean_repo,
        escalation_bundle_path=bundle_path,
    )

    assert bridge_result["success"] is True, bridge_result.get("stderr", "")
    assert lean_cert_out.exists()
    assert isinstance(bridge_result["lean_cert"], dict)
    candidate = bridge_result["lean_cert"]["candidates"][0]
    assert candidate["name"] == LEAN_PROOF_ATOM
    assert candidate["z3_check_result"] == "lean_verified"
    assert candidate["lean_metadata"]["known_witness_used"] is False


def test_lean_fallback_upgrades_multiple_unknown_atoms(
    tmp_path: Path,
    mumei_lean_repo: Path,
    std_multi_unknown_cert: dict,
) -> None:
    cert_path = tmp_path / "std-multi.proof-cert.json"
    lean_cert_out = tmp_path / "std-multi.lean-cert.json"
    cert_path.write_text(json.dumps(std_multi_unknown_cert), encoding="utf-8")

    bridge_result = lean_bridge.run_lean_bridge(
        cert_path=cert_path,
        lean_cert_out=lean_cert_out,
        mumei_lean_repo=mumei_lean_repo,
    )

    assert bridge_result["success"] is True, bridge_result.get("stderr", "")
    upgraded = lean_bridge.merge_lean_cert_into_proof_cert(
        std_multi_unknown_cert,
        bridge_result["lean_cert"],
    )
    atoms = {atom["name"]: atom for atom in upgraded["atoms"]}
    assert atoms["abs_saturating"]["z3_check_result"] == "lean_verified"
    assert atoms["abs_saturating"]["lean_metadata"]["known_witness_used"] is False
    assert atoms["list_length"]["z3_check_result"] == "lean_verified"
    assert upgraded["all_verified"] is True


def test_proliferate_lean_fallback_summary_json(
    tmp_path: Path,
    mumei_lean_repo: Path,
    std_abs_unknown_cert: dict,
) -> None:
    probe_cert = tmp_path / "probe.proof-cert.json"
    probe_out = tmp_path / "probe.lean-cert.json"
    probe_cert.write_text(json.dumps(std_abs_unknown_cert), encoding="utf-8")
    probe = lean_bridge.run_lean_bridge(
        cert_path=probe_cert,
        lean_cert_out=probe_out,
        mumei_lean_repo=mumei_lean_repo,
    )
    assert probe["success"] is True, probe.get("stderr", "")

    std = tmp_path / "std"
    std.mkdir()
    summary_path = tmp_path / "summary.json"
    fake_code = "atom core_ok(x: i64) ensures: true; body: x;\n"

    with patch("agent.proliferate.generate_code") as gen_mock, patch(
        "agent.proliferate.AgentConfig"
    ) as cfg_mock, patch(
        "agent.proliferate.create_mumei_client"
    ) as client_mock, patch(
        "agent.proliferate.analyze_gaps"
    ) as gaps_mock, patch(
        "agent.proliferate.generate_specs_from_gaps"
    ) as specs_mock, patch(
        "agent.proliferate.publish"
    ) as publish_mock:
        gaps_mock.return_value = {"proposals": [{"name": "std/core.mm"}]}
        specs_mock.return_value = [
            {"task_id": "lean-fallback-e2e", "target_file": "std/core.mm"}
        ]
        gen_mock.return_value = (fake_code, True)
        cfg = MagicMock()
        cfg.mumei_bin = "mumei"
        cfg.model = "gpt-test"
        cfg.max_retries = 1
        cfg.mumei_lean_repo = str(mumei_lean_repo)
        cfg.create_client.return_value = MagicMock()
        cfg_mock.return_value = cfg
        client = MagicMock()
        # ``_attach_dry_run_proof_certificate`` stores ``report`` as the
        # proof certificate that ``_run_lean_fallback`` later inspects
        # for ``unknown`` atoms. An empty dict would be treated as falsy
        # by the ``cert.get(...) or ...`` chain in ``_run_lean_fallback``
        # and the spec would be silently skipped, so the assertions
        # below (``fallback["attempted"] is True`` /
        # ``fallback["proved"] > 0``) would never hold. Supply the
        # fixture cert (with a single ``unknown`` atom) so the bridge
        # actually has something to discharge.
        client.verify.return_value = {
            "success": True,
            "report": std_abs_unknown_cert,
        }
        client_mock.return_value = client
        publish_mock.return_value = {
            "success": True,
            "generated_file": "std/core.mm",
            "proof_certificate": std_abs_unknown_cert,
            "artifacts": [],
        }

        results = proliferate_mod.proliferate(
            tmp_path,
            dry_run=True,
            max_proposals=1,
            output_json=summary_path,
            enable_lean_fallback=True,
        )

    assert results[0]["success"] is True
    upgraded_atom = results[0]["publish_result"]["proof_certificate"]["atoms"][0]
    assert upgraded_atom["z3_check_result"] == "lean_verified"
    assert upgraded_atom["lean_metadata"]["known_witness_used"] is False
    data = json.loads(summary_path.read_text(encoding="utf-8"))
    assert data["lean_fallback_enabled"] is True
    assert "lean_fallback_metrics" in data
    assert all(
        detail["lean_fallback"]["proved"] > 0
        for detail in data["details"]
    )
    fallback = data["details"][0]["lean_fallback"]
    assert fallback["attempted"] is True
    assert fallback["proved"] > 0
    cert_summary = data["details"][0]["publish_result"][
        "proof_certificate_summary"
    ]
    assert cert_summary["lean_verified_count"] == 1
    assert cert_summary["all_verified"] is True
    assert data["details"][0]["upgraded_cert_summary"][
        "lean_verified_count"
    ] == 1
    assert data["lean_fallback_attempted"] >= 1
    assert data["lean_fallback_proved"] >= 1
    assert data["lean_fallback_failed"] == 0
    assert data["lean_fallback_success_rate"] >= 0.70
    assert data["lean_fallback_partial_successes"] == 0
    assert data["lean_fallback_duration_seconds"]["count"] >= 1


def test_lean_fallback_summary_records_no_unknowns() -> None:
    results = [
        {
            "success": True,
            "publish_result": {
                "success": True,
                "proof_certificate": {
                    "atoms": [
                        {
                            "name": "already_proved",
                            "z3_check_result": "unsat",
                            "status": "verified",
                        }
                    ]
                },
            },
        }
    ]

    proliferate_mod._run_lean_fallback(results, mumei_lean_repo=None)

    fallback = results[0]["lean_fallback"]
    assert fallback["attempted"] is False
    assert fallback["unknown_count"] == 0
    assert fallback["proved"] == 0
    assert fallback["failed"] == 0
    assert fallback["success"] is True


def test_lean_fallback_gracefully_records_unavailable_repo(
    std_abs_unknown_cert: dict,
) -> None:
    results = [
        {
            "success": True,
            "publish_result": {
                "success": True,
                "proof_certificate": std_abs_unknown_cert,
            },
        }
    ]

    proliferate_mod._run_lean_fallback(results, mumei_lean_repo=None)

    fallback = results[0]["lean_fallback"]
    assert fallback["attempted"] is True
    assert fallback["unknown_count"] == 1
    assert fallback["proved"] == 0
    assert fallback["failed"] == 1
    assert fallback["success"] is False
    assert fallback["error_code"] == "lean_unavailable"


def test_lean_bridge_gracefully_degrades_without_lake(
    tmp_path: Path,
    mumei_lean_repo: Path,
    std_abs_unknown_cert: dict,
) -> None:
    cert_path = tmp_path / "std-abs.proof-cert.json"
    lean_cert_out = tmp_path / "std-abs.lean-cert.json"
    cert_path.write_text(json.dumps(std_abs_unknown_cert), encoding="utf-8")

    with patch("agent.lean_bridge.shutil.which", return_value=None):
        bridge_result = lean_bridge.run_lean_bridge(
            cert_path=cert_path,
            lean_cert_out=lean_cert_out,
            mumei_lean_repo=mumei_lean_repo,
        )

    assert bridge_result["success"] is False
    assert bridge_result["error_code"] == "lake_missing"
    assert bridge_result["retryable"] is True
