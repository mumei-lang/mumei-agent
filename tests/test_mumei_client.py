"""Tests for MumeiClient command construction."""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from agent.mumei_client import MumeiClient


def test_verify_command_default():
    """Test that verify constructs correct command with default binary."""
    client = MumeiClient()
    with patch("agent.mumei_client.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0, stdout='{"status":"success"}', stderr=""
        )
        result = client.verify("test.mm")
        call_args = mock_run.call_args[0][0]
        assert call_args == ["mumei", "verify", "--json", "test.mm"]
        assert result["success"] is True
        assert result["report"]["status"] == "success"


def test_verify_command_with_report_dir():
    """Test that verify includes --report-dir when specified."""
    client = MumeiClient()
    with patch("agent.mumei_client.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0, stdout="{}", stderr=""
        )
        client.verify("test.mm", report_dir="/tmp/reports")
        call_args = mock_run.call_args[0][0]
        assert call_args == [
            "mumei", "verify", "--json",
            "--report-dir", "/tmp/reports",
            "test.mm",
        ]


def test_verify_collect_decidable_metrics_embeds_report():
    """Test that decidable metrics are requested and attached to reports."""
    client = MumeiClient()
    metrics_paths: list[Path] = []

    def fake_run(cmd, capture_output=True, text=True):
        metrics_path = Path(cmd[cmd.index("--output") + 1])
        metrics_paths.append(metrics_path)
        metrics_path.write_text(
            '{"total_atoms_checked":1,"atoms_with_warnings":1,'
            '"warning_counts":{"nonlinear_arithmetic":1}}',
            encoding="utf-8",
        )
        return MagicMock(returncode=0, stdout='{"status":"success"}', stderr="")

    with patch("agent.mumei_client.subprocess.run", side_effect=fake_run) as mock_run:
        result = client.verify("test.mm", collect_decidable_metrics=True)
        call_args = mock_run.call_args[0][0]
        assert call_args[:5] == [
            "mumei", "verify", "--json", "--emit", "decidable-metrics",
        ]
        assert "--output" in call_args
        assert result["success"] is True
        assert result["report"]["decidable_fragment"]["total_atoms_checked"] == 1
        assert result["report"]["decidable_fragment"]["warning_counts"] == {
            "nonlinear_arithmetic": 1,
        }
        assert metrics_paths and not metrics_paths[0].exists()


def test_verify_collect_decidable_metrics_falls_back_when_unsupported():
    """Test that older mumei binaries still work without metrics emit support."""
    client = MumeiClient()
    with patch("agent.mumei_client.subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(
                returncode=2,
                stdout="",
                stderr="error: unexpected argument '--emit' found",
            ),
            MagicMock(returncode=0, stdout='{"status":"success"}', stderr=""),
        ]
        result = client.verify("test.mm", collect_decidable_metrics=True)
        first_call = mock_run.call_args_list[0][0][0]
        second_call = mock_run.call_args_list[1][0][0]
        assert "--emit" in first_call
        assert second_call == ["mumei", "verify", "--json", "test.mm"]
        assert result["success"] is True


def test_verify_includes_spec_code_mapping():
    """Test verify can attach spec-code mapping to reports."""
    client = MumeiClient()
    mapping = [{"spec_item_id": "safe_add"}]
    with patch("agent.mumei_client.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0, stdout='{"status":"success"}', stderr=""
        )
        result = client.verify("test.mm", spec_code_mapping=mapping)
        assert result["spec_code_mapping"] == mapping
        assert result["report"]["spec_code_mapping"] == mapping


def test_verify_failure_attaches_loss_vector():
    """Test verify enriches failed JSON reports with --emit loss-vector output."""
    client = MumeiClient()
    loss_vector = {
        "status": "verification_failed",
        "error_type": "postcondition_violated",
        "location": {"file": "test.mm", "line": 1},
        "reconstruction_loss": {"violated_property": "result > 0"},
        "feedback_instruction": "repair",
    }
    with patch("agent.mumei_client.subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout='{"status":"failed"}', stderr="failed"),
            MagicMock(returncode=1, stdout=json.dumps(loss_vector), stderr="failed"),
        ]
        result = client.verify("test.mm")
        first_call = mock_run.call_args_list[0][0][0]
        second_call = mock_run.call_args_list[1][0][0]
        assert first_call == ["mumei", "verify", "--json", "test.mm"]
        assert second_call == ["mumei", "verify", "--emit", "loss-vector", "test.mm"]
        assert result["success"] is False
        assert result["loss_vector"] == loss_vector
        assert result["report"]["structured_feedback"] == loss_vector


def test_verify_command_cargo_run():
    """Test that cargo run style invocation splits correctly."""
    client = MumeiClient("cargo run --manifest-path /path/Cargo.toml --")
    with patch("agent.mumei_client.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0, stdout="{}", stderr=""
        )
        client.verify("test.mm")
        call_args = mock_run.call_args[0][0]
        assert call_args == [
            "cargo", "run", "--manifest-path", "/path/Cargo.toml", "--",
            "verify", "--json", "test.mm",
        ]


def test_build_command():
    """Test that build constructs correct command."""
    client = MumeiClient()
    with patch("agent.mumei_client.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0, stdout="Built OK", stderr=""
        )
        result = client.build("test.mm", output="blade")
        call_args = mock_run.call_args[0][0]
        assert call_args == ["mumei", "build", "test.mm", "-o", "blade"]
        assert result["success"] is True


def test_verify_failure():
    """Test that failure is reported correctly."""
    client = MumeiClient()
    with patch("agent.mumei_client.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout='{"status":"failed","reason":"division by zero"}',
            stderr="Error: verification failed",
        )
        result = client.verify("test.mm")
        assert result["success"] is False
        assert result["report"]["status"] == "failed"
        assert "Error" in result["stderr"]


def test_verify_invalid_json():
    """Test handling of non-JSON output."""
    client = MumeiClient()
    with patch("agent.mumei_client.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1, stdout="not json", stderr=""
        )
        result = client.verify("test.mm")
        assert result["success"] is False
        assert result["report"] == {}


# --- infer_effects / infer_contracts tests ---


def test_infer_effects_success():
    """Test infer_effects with successful JSON output."""
    client = MumeiClient()
    with patch("agent.mumei_client.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"effects": ["FileRead", "Log"]}',
            stderr="",
        )
        result = client.infer_effects("test.mm")
        call_args = mock_run.call_args[0][0]
        assert call_args == ["mumei", "infer-effects", "test.mm"]
        assert result["success"] is True
        assert result["analysis"]["effects"] == ["FileRead", "Log"]


def test_infer_effects_failure():
    """Test infer_effects when command fails."""
    client = MumeiClient()
    with patch("agent.mumei_client.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="Error"
        )
        result = client.infer_effects("test.mm")
        assert result["success"] is False
        assert result["analysis"] == {}


def test_infer_effects_invalid_json():
    """Test infer_effects with non-JSON output."""
    client = MumeiClient()
    with patch("agent.mumei_client.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0, stdout="not json", stderr=""
        )
        result = client.infer_effects("test.mm")
        assert result["success"] is False
        assert result["analysis"] == {}


def test_infer_contracts_success():
    """Test infer_contracts with successful JSON output."""
    client = MumeiClient()
    with patch("agent.mumei_client.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"contracts": [{"name": "add", "requires": "a > 0"}]}',
            stderr="",
        )
        result = client.infer_contracts("test.mm")
        call_args = mock_run.call_args[0][0]
        assert call_args == ["mumei", "infer-contracts", "test.mm"]
        assert result["success"] is True
        assert result["analysis"]["contracts"][0]["name"] == "add"


def test_infer_contracts_failure():
    """Test infer_contracts when command fails."""
    client = MumeiClient()
    with patch("agent.mumei_client.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="Error"
        )
        result = client.infer_contracts("test.mm")
        assert result["success"] is False
        assert result["analysis"] == {}


def test_infer_contracts_cargo_run():
    """Test infer_contracts with cargo run style invocation."""
    client = MumeiClient("cargo run --")
    with patch("agent.mumei_client.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0, stdout='{}', stderr=""
        )
        client.infer_contracts("test.mm")
        call_args = mock_run.call_args[0][0]
        assert call_args == ["cargo", "run", "--", "infer-contracts", "test.mm"]
