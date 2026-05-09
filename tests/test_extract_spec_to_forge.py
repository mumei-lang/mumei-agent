"""Tests for extract-spec → forge pipeline wiring."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent.extract_spec import build_parser, main


def _make_response(text: str) -> MagicMock:
    message = MagicMock()
    message.content = text
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _mock_client(response_text: str) -> MagicMock:
    client = MagicMock()
    client.chat.completions.create.return_value = _make_response(response_text)
    return client


def test_extract_spec_forge_option_parses() -> None:
    args = build_parser().parse_args(
        [
            "--text",
            "絶対値関数。結果は常に非負。",
            "--domain",
            "math",
            "--output",
            "spec.json",
            "--forge",
            "--forge-dry-run",
        ]
    )

    assert args.forge is True
    assert args.forge_dry_run is True
    assert args.domain == "math"


def test_extract_spec_to_forge_to_verify_with_mocks(tmp_path: Path) -> None:
    spec = {
        "task_id": "nl-abs-i64",
        "target_file": "std/math/abs_i64.mm",
        "mode": "create",
        "atoms": [
            {
                "name": "abs_i64",
                "description": "Absolute value for i64",
                "inputs": [{"name": "x", "type": "i64"}],
                "return_type": "i64",
                "requires": "x > i64::MIN",
                "ensures": "result >= 0",
                "effects": [],
            }
        ],
        "max_retries": 2,
        "auto_commit": False,
    }
    generated_code = "atom abs_i64(x: i64)\n    requires: x > i64::MIN;\n    ensures: result >= 0;\n    body: if x < 0 { -x } else { x };\n"
    output_path = tmp_path / "extracted.json"
    tasks_dir = tmp_path / "forge_tasks"
    mumei_repo = tmp_path / "mumei"
    (mumei_repo / "std" / "math").mkdir(parents=True)
    log_path = tmp_path / "forge_log.json"

    fake_config = MagicMock()
    fake_config.model = "test-model"
    fake_config.max_retries = 2
    fake_config.mumei_bin = "mumei"
    fake_config.create_client.return_value = _mock_client(json.dumps(spec))

    mumei_client = MagicMock()
    mumei_client.verify.return_value = {"success": True, "report": {}, "stdout": "", "stderr": ""}

    args = build_parser().parse_args(
        [
            "--text",
            "絶対値関数。負の入力は正に変換し、結果は常に非負。",
            "--domain",
            "math",
            "--output",
            str(output_path),
            "--forge",
            "--forge-tasks-dir",
            str(tasks_dir),
            "--mumei-repo",
            str(mumei_repo),
            "--forge-log-path",
            str(log_path),
        ]
    )

    with patch("agent.extract_spec.AgentConfig", return_value=fake_config), patch(
        "agent.extract_spec.create_mumei_client", return_value=mumei_client
    ), patch("agent.forge.generate_code", return_value=(generated_code, True)) as mock_generate:
        main(args)

    assert json.loads(output_path.read_text(encoding="utf-8")) == spec
    forge_spec_path = tasks_dir / "nl-abs-i64.json"
    assert json.loads(forge_spec_path.read_text(encoding="utf-8")) == spec

    target_path = mumei_repo / "std" / "math" / "abs_i64.mm"
    assert target_path.read_text(encoding="utf-8") == generated_code
    mumei_client.verify.assert_called_once_with(str(target_path))
    mock_generate.assert_called_once()
    assert mock_generate.call_args.kwargs["mumei_client"] is mumei_client

    forge_log = json.loads(log_path.read_text(encoding="utf-8"))
    assert forge_log["runs"][0]["task_id"] == "nl-abs-i64"
    assert forge_log["runs"][0]["status"] == "success"


def test_extract_spec_generate_and_forge_uses_raw_forge_spec(tmp_path: Path) -> None:
    spec = {
        "task_id": "nl-abs-i64",
        "target_file": "std/math/abs_i64.mm",
        "mode": "create",
        "atoms": [
            {
                "name": "abs_i64",
                "description": "Absolute value for i64",
                "inputs": [{"name": "x", "type": "i64"}],
                "return_type": "i64",
                "requires": "x > i64::MIN",
                "ensures": "result >= 0",
                "effects": [],
            }
        ],
    }
    normalized_spec = {
        "name": "abs_i64",
        "description": "Absolute value for i64",
        "params": [{"name": "x", "type": "i64"}],
        "return_type": "i64",
        "requires": "x > i64::MIN",
        "ensures": "result >= 0",
    }
    generated_code = "atom abs_i64(x: i64) -> i64 { if x < 0 { -x } else { x } }\n"
    forge_code = "atom abs_i64(x: i64)\n    ensures: result >= 0;\n    body: if x < 0 { -x } else { x };\n"
    output_path = tmp_path / "generated_spec.json"
    generate_output_path = tmp_path / "generated.mm"
    tasks_dir = tmp_path / "forge_tasks"
    mumei_repo = tmp_path / "mumei"
    (mumei_repo / "std" / "math").mkdir(parents=True)
    log_path = tmp_path / "forge_log.json"

    fake_config = MagicMock()
    fake_config.model = "test-model"
    fake_config.max_retries = 2
    fake_config.mumei_bin = "mumei"
    fake_config.create_client.return_value = _mock_client(json.dumps(spec))

    mumei_client = MagicMock()
    mumei_client.verify.return_value = {"success": True, "report": {}, "stdout": "", "stderr": ""}

    args = build_parser().parse_args(
        [
            "--text",
            "絶対値関数。負の入力は正に変換し、結果は常に非負。",
            "--domain",
            "math",
            "--output",
            str(output_path),
            "--generate",
            "--generate-output",
            str(generate_output_path),
            "--forge",
            "--forge-tasks-dir",
            str(tasks_dir),
            "--mumei-repo",
            str(mumei_repo),
            "--forge-log-path",
            str(log_path),
        ]
    )

    with patch("agent.extract_spec.AgentConfig", return_value=fake_config), patch(
        "agent.extract_spec.create_mumei_client", return_value=mumei_client
    ), patch(
        "agent.strategies.spec_refinement.run_refinement_loop",
        return_value=(generated_code, True, normalized_spec),
    ), patch("agent.forge.generate_code", return_value=(forge_code, True)):
        main(args)

    assert json.loads(output_path.read_text(encoding="utf-8")) == normalized_spec
    assert generate_output_path.read_text(encoding="utf-8") == generated_code
    forge_spec_path = tasks_dir / "nl-abs-i64.json"
    assert json.loads(forge_spec_path.read_text(encoding="utf-8")) == spec
    assert (mumei_repo / "std" / "math" / "abs_i64.mm").read_text(encoding="utf-8") == forge_code
    forge_log = json.loads(log_path.read_text(encoding="utf-8"))
    assert forge_log["runs"][0]["status"] == "success"
