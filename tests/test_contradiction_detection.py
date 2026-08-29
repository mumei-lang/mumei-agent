"""Tests for natural-language contradiction-only flows."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent import mcp_server
from agent.extract_spec import (
    build_parser,
    check_spec_contradiction_from_spec,
    main,
)


def _payload(raw: str) -> dict:
    assert isinstance(raw, str)
    return json.loads(raw)


def test_check_contradiction_only_option_parses() -> None:
    args = build_parser().parse_args(
        [
            "--text",
            "x は 0 より大きく、同時に 0 未満。",
            "--output",
            "report.json",
            "--check-contradiction-only",
        ]
    )

    assert args.check_contradiction_only is True


def test_check_spec_contradiction_from_spec_builds_temporary_trusted_atoms() -> None:
    spec = {
        "atoms": [
            {
                "name": "impossible_x",
                "inputs": [{"name": "x", "type": "i64"}],
                "return_type": "i64",
                "requires": "x > 0 && x < 0",
                "ensures": "result == x",
                "effects": [],
            }
        ]
    }
    mumei = MagicMock()
    captured: dict[str, str] = {}

    def fake_verify(source_path: str, report_dir: str) -> dict:
        captured["source"] = Path(source_path).read_text(encoding="utf-8")
        captured["report_dir"] = report_dir
        return {
            "success": False,
            "report": {},
            "stdout": "",
            "stderr": "Spec contradiction in atom 'impossible_x': requires clause is unsatisfiable",
        }

    mumei.verify.side_effect = fake_verify

    result = check_spec_contradiction_from_spec(spec, mumei)

    assert result["contradiction_found"] is True
    assert result["contradiction_type"] == "spec_internal"
    assert "direct contradiction" in result["natural_language_explanation"]
    assert "trusted atom impossible_x" in captured["source"]


def test_check_spec_contradiction_from_spec_handles_failed_json_summary() -> None:
    spec = {
        "atoms": [
            {
                "name": "impossible_x",
                "inputs": [{"name": "x", "type": "i64"}],
                "return_type": "i64",
                "requires": "x > 0 && x < 0",
                "ensures": "result == x",
            }
        ]
    }
    mumei = MagicMock()
    mumei.verify.return_value = {
        "success": False,
        "report": {
            "status": "failed",
            "verified": 0,
            "failed": 1,
            "skipped": 0,
            "escalation_candidates": 0,
        },
        "stdout": '{\n  "status": "failed",\n  "failed": 1\n}\n',
        "stderr": "",
    }

    result = check_spec_contradiction_from_spec(spec, mumei)

    assert result["contradiction_found"] is True
    assert result["contradiction_type"] == "spec_internal"
    assert "SpecValidation failed" in result["natural_language_explanation"]
    assert "1 failed atom" in result["natural_language_explanation"]


def test_extract_spec_cli_check_contradiction_only_writes_report(tmp_path: Path) -> None:
    output = tmp_path / "contradiction.json"
    spec = {
        "task_id": "impossible",
        "target_file": "std/impossible.mm",
        "mode": "create",
        "atoms": [
            {
                "name": "impossible_x",
                "description": "Impossible bounds",
                "inputs": [{"name": "x", "type": "i64"}],
                "return_type": "i64",
                "requires": "x > 0 && x < 0",
                "ensures": "result == x",
                "effects": [],
            }
        ],
    }
    fake_config = MagicMock()
    fake_config.model = "m"
    fake_config.mumei_bin = "mumei"
    fake_config.create_client.return_value = MagicMock()
    mumei = MagicMock()

    with patch("agent.extract_spec.AgentConfig", return_value=fake_config), patch(
        "agent.extract_spec.create_mumei_client", return_value=mumei
    ), patch("agent.extract_spec.extract_spec", return_value=spec), patch(
        "agent.extract_spec.check_spec_contradiction_from_spec",
        return_value={
            "contradiction_found": True,
            "contradiction_type": "spec_internal",
            "natural_language_explanation": "The spec is contradictory.",
            "verification": {"success": False},
        },
    ):
        args = build_parser().parse_args(
            [
                "--text",
                "矛盾仕様",
                "--output",
                str(output),
                "--check-contradiction-only",
            ]
        )
        main(args)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["contradiction_found"] is True
    assert payload["spec"] == spec


def test_mcp_check_spec_contradiction_delegates_to_extract_spec() -> None:
    with patch(
        "agent.mcp_server.extract_spec",
        return_value=json.dumps({"status": "ok", "contradiction_found": True}),
    ) as mock_extract:
        payload = _payload(mcp_server.check_spec_contradiction("矛盾仕様", "math"))

    assert payload["status"] == "ok"
    assert payload["contradiction_found"] is True
    mock_extract.assert_called_once_with(
        "矛盾仕様",
        domain_hint="math",
        check_contradiction_only=True,
    )


def test_mcp_extract_spec_contradiction_only_uses_mumei_repo_binary(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "mumei"
    debug_bin = repo / "target" / "debug" / "mumei"
    debug_bin.parent.mkdir(parents=True)
    debug_bin.write_text("#!/bin/sh\n", encoding="utf-8")

    fake_config = MagicMock()
    fake_config.model = "m"
    fake_config.mumei_bin = "configured-mumei"
    fake_config.create_client.return_value = MagicMock()
    mumei = MagicMock()
    spec = {
        "task_id": "impossible",
        "target_file": "std/impossible.mm",
        "mode": "create",
        "atoms": [
            {
                "name": "impossible_x",
                "description": "Impossible bounds",
                "inputs": [{"name": "x", "type": "i64"}],
                "return_type": "i64",
                "requires": "x > 0 && x < 0",
                "ensures": "result == x",
                "effects": [],
            }
        ],
    }

    with patch("agent.config.AgentConfig", return_value=fake_config), patch(
        "agent.mumei_client.create_mumei_client", return_value=mumei
    ) as mock_create_mumei, patch(
        "agent.spec_extractor.extract_spec", return_value=spec
    ), patch(
        "agent.extract_spec.check_spec_contradiction_from_spec",
        return_value={
            "contradiction_found": True,
            "contradiction_type": "spec_internal",
            "natural_language_explanation": "The spec is contradictory.",
            "verification": {"success": False},
        },
    ):
        payload = _payload(
            mcp_server.extract_spec(
                "矛盾仕様",
                mumei_repo=str(repo),
                check_contradiction_only=True,
            )
        )

    assert payload["status"] == "ok"
    assert payload["contradiction_found"] is True
    mock_create_mumei.assert_called_once_with(str(debug_bin))


def test_mcp_check_cross_spec_consistency_reads_report(tmp_path: Path) -> None:
    first = tmp_path / "a.mm"
    second = tmp_path / "b.mm"
    first.write_text("atom a() -> i64 { requires: true; ensures: result >= 0; body: { 0 } }")
    second.write_text("atom b() -> i64 { requires: true; ensures: result < 0; body: { -1 } }")

    fake_config = MagicMock()
    fake_config.mumei_bin = "mumei"
    mumei = MagicMock()

    def fake_verify(_source_path: str, report_dir: str, extra_args: list[str]) -> dict:
        report_path = Path(report_dir) / "cross_spec.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(
                {
                    "summary": {
                        "inconsistent_calls": 0,
                        "global_invariant_conflict_count": 1,
                    }
                }
            ),
            encoding="utf-8",
        )
        assert extra_args == ["--cross-spec-verify", "--cross-spec-files", str(second)]
        return {"success": True, "report": {}, "stdout": "", "stderr": ""}

    mumei.verify.side_effect = fake_verify

    with patch("agent.config.AgentConfig", return_value=fake_config), patch(
        "agent.mumei_client.create_mumei_client", return_value=mumei
    ):
        payload = _payload(
            mcp_server.check_cross_spec_consistency(json.dumps([str(first), str(second)]))
        )

    assert payload["status"] == "ok"
    assert payload["consistent"] is False
    assert payload["cross_spec"]["summary"]["global_invariant_conflict_count"] == 1


def test_mcp_check_cross_spec_consistency_maps_session_violations(tmp_path: Path) -> None:
    spec = tmp_path / "payment_client.mm"
    spec.write_text("atom payment_client_request() body: 0;\n", encoding="utf-8")
    report = json.loads(
        (Path(__file__).parent / "fixtures" / "cross_spec_session_violation.json").read_text(
            encoding="utf-8"
        )
    )

    fake_config = MagicMock()
    fake_config.mumei_bin = "mumei"
    mumei = MagicMock()

    def fake_verify(_source_path: str, report_dir: str, extra_args: list[str]) -> dict:
        report_path = Path(report_dir) / "cross_spec.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report), encoding="utf-8")
        return {"success": False, "report": {}, "stdout": "", "stderr": ""}

    mumei.verify.side_effect = fake_verify

    with patch("agent.config.AgentConfig", return_value=fake_config), patch(
        "agent.mumei_client.create_mumei_client", return_value=mumei
    ):
        payload = _payload(mcp_server.check_cross_spec_consistency(json.dumps([str(spec)])))

    assert payload["status"] == "ok"
    assert payload["consistent"] is False
    assert payload["session_protocol_violations"][0]["effect"] == "PaymentChannel"
    assert len(payload["missing_constraints"]) == 1
    assert "deadlock_no_progress" in payload["missing_constraints"][0]
    assert payload["session_analysis_skips"] == []
