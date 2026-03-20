"""Tests for MumeiClient command construction."""
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
