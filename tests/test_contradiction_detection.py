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
    assert "direct contradiction" in result["natural_language_explanation"]
    assert "trusted atom impossible_x" in captured["source"]


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
