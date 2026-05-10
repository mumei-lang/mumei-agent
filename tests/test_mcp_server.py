"""Unit tests for ``agent.mcp_server`` (P10).

Each MCP tool is exercised directly as a Python function — the FastMCP
transport is not booted.  External dependencies (``MumeiClient``,
``AgentConfig``, ``MumeiForge``) are patched so the suite stays
hermetic: no LLM calls, no mumei binary required.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent import mcp_server


def _payload(raw: str) -> dict:
    """Parse the JSON-encoded tool result."""
    assert isinstance(raw, str)
    return json.loads(raw)


# ---------------------------------------------------------------------------
# get_agent_status
# ---------------------------------------------------------------------------


class TestGetAgentStatus:
    def test_returns_expected_fields(self) -> None:
        result = _payload(mcp_server.get_agent_status())
        assert result["status"] == "ok"
        assert "model" in result
        assert "mumei_bin" in result
        assert "mcp-server" in result["subcommands"]
        assert set(result["mcp_tools"]) >= {
            "forge_task",
            "heal_file",
            "measure_std_health",
            "propose_forge_tasks",
            "list_forge_log",
            "get_agent_status",
            "send_latent_message",
        }
        assert "PREFER_MCP_GAPS" in result["feature_flags"]
        assert "ENABLE_LATENT_PROTOCOL" in result["feature_flags"]

    def test_status_tools_match_registered_tools(self) -> None:
        result = _payload(mcp_server.get_agent_status())
        registered = set(mcp_server.mcp._tool_manager._tools)
        assert set(result["mcp_tools"]) == registered
        assert "send_latent_message" in registered


# ---------------------------------------------------------------------------
# forge_task
# ---------------------------------------------------------------------------


class TestForgeTask:
    def test_invalid_json_returns_error(self, tmp_path: Path) -> None:
        result = _payload(
            mcp_server.forge_task("{not json", str(tmp_path), dry_run=True)
        )
        assert result["status"] == "error"
        assert "valid JSON" in result["error"]

    def test_missing_repo_returns_error(self) -> None:
        result = _payload(
            mcp_server.forge_task('{"task_id":"x"}', "/no/such/path/exists")
        )
        assert result["status"] == "error"
        assert "does not exist" in result["error"]

    def test_dry_run_short_circuits(self, tmp_path: Path) -> None:
        result = _payload(
            mcp_server.forge_task(
                json.dumps(
                    {
                        "task_id": "demo",
                        "target_file": "std/demo.mm",
                        "atoms": [{"name": "demo"}],
                    }
                ),
                str(tmp_path),
                dry_run=True,
            )
        )
        assert result["task_id"] == "demo"
        assert result["status"] == "skipped"
        assert result["error"] == "dry-run"
        assert result["code_length"] == 0
        assert result["dry_run"] is True

    def test_real_run_calls_forge_one(self, tmp_path: Path) -> None:
        # Pretend the LLM is available and a fake MumeiForge produces a
        # successful ForgeResult.
        from agent.forge import ForgeResult

        target = tmp_path / "std" / "demo.mm"
        target.parent.mkdir(parents=True)
        target.write_text("// generated\n", encoding="utf-8")

        fake_result = ForgeResult(
            task_id="demo",
            status="success",
            attempts=1,
            target_file="std/demo.mm",
            atoms_added=["demo"],
        )

        fake_config = MagicMock()
        fake_config.mumei_bin = "mumei"
        fake_config.create_client.return_value = MagicMock()

        fake_forge = MagicMock()
        fake_forge.forge_one.return_value = fake_result

        with patch(
            "agent.config.AgentConfig", return_value=fake_config
        ), patch("agent.forge.MumeiForge", return_value=fake_forge), patch(
            "agent.mumei_client.MumeiClient"
        ):
            result = _payload(
                mcp_server.forge_task(
                    json.dumps(
                        {
                            "task_id": "demo",
                            "target_file": "std/demo.mm",
                            "atoms": [{"name": "demo"}],
                        }
                    ),
                    str(tmp_path),
                    dry_run=False,
                )
            )

        assert result["status"] == "success"
        assert result["task_id"] == "demo"
        assert result["target_file"] == "std/demo.mm"
        assert result["code_length"] == len("// generated\n")
        fake_forge.forge_one.assert_called_once()


# ---------------------------------------------------------------------------
# heal_file
# ---------------------------------------------------------------------------


class TestHealFile:
    def test_empty_source_returns_error(self) -> None:
        result = _payload(mcp_server.heal_file("   "))
        assert result["status"] == "error"

    def test_calls_get_fix(self) -> None:
        fake_config = MagicMock()
        fake_config.mumei_bin = "mumei"
        fake_config.model = "gpt-4o"
        fake_config.strategy = "single"
        fake_config.create_client.return_value = MagicMock()

        with patch(
            "agent.config.AgentConfig", return_value=fake_config
        ), patch(
            "agent.strategies.fix_strategy.get_fix",
            return_value="atom fixed() ensures: true; body: 0;",
        ) as mock_fix:
            result = _payload(
                mcp_server.heal_file(
                    "atom broken() ensures: false; body: 0;",
                    error_report=json.dumps({"failure_type": "postcondition"}),
                )
            )

        mock_fix.assert_called_once()
        assert result["status"] == "ok"
        assert result["success"] is True
        assert "atom fixed" in result["healed_code"]


# ---------------------------------------------------------------------------
# measure_std_health
# ---------------------------------------------------------------------------


class TestMeasureStdHealth:
    def test_missing_std_returns_error(self, tmp_path: Path) -> None:
        result = _payload(mcp_server.measure_std_health(str(tmp_path)))
        assert result["status"] == "error"
        assert "std directory not found" in result["error"]

    def test_calls_measure_health(self, tmp_path: Path) -> None:
        std = tmp_path / "std"
        std.mkdir()
        sentinel = {
            "total_files": 0,
            "verified_files": 0,
            "failed_files": 0,
            "total_atoms": 0,
            "verified_atoms": 0,
            "trusted_atoms": 0,
            "health_score": 0.0,
            "todo_count": 0,
            "details": [],
        }
        with patch(
            "agent.std_health.measure_health", return_value=sentinel
        ) as mock_measure:
            result = _payload(mcp_server.measure_std_health(str(tmp_path)))
        mock_measure.assert_called_once()
        assert result["status"] == "ok"
        assert result["health_score"] == 0.0


# ---------------------------------------------------------------------------
# propose_forge_tasks
# ---------------------------------------------------------------------------


class TestProposeForgeTasks:
    def test_invalid_max_returns_error(self, tmp_path: Path) -> None:
        std = tmp_path / "std"
        std.mkdir()
        result = _payload(
            mcp_server.propose_forge_tasks(str(tmp_path), max_proposals=0)
        )
        assert result["status"] == "error"

    def test_missing_std_returns_error(self, tmp_path: Path) -> None:
        result = _payload(mcp_server.propose_forge_tasks(str(tmp_path)))
        assert result["status"] == "error"

    def test_returns_proposals_and_specs(self, tmp_path: Path) -> None:
        std = tmp_path / "std"
        std.mkdir()
        result = _payload(
            mcp_server.propose_forge_tasks(str(tmp_path), max_proposals=2)
        )
        assert result["status"] == "ok"
        assert isinstance(result["proposals"], list)
        assert isinstance(result["specs"], list)
        # Empty std/ triggers at least the std/core.mm rule.
        assert any(p["name"] == "std/core.mm" for p in result["proposals"])


# ---------------------------------------------------------------------------
# list_forge_log
# ---------------------------------------------------------------------------


class TestListForgeLog:
    def test_missing_log_is_ok(self, tmp_path: Path) -> None:
        result = _payload(
            mcp_server.list_forge_log(str(tmp_path / "nope.json"))
        )
        assert result["status"] == "ok"
        assert result["count"] == 0
        assert result["entries"] == []

    def test_reads_list_log(self, tmp_path: Path) -> None:
        log = tmp_path / "forge_log.json"
        entries = [
            {"task_id": "a", "status": "success"},
            {"task_id": "b", "status": "failed"},
        ]
        log.write_text(json.dumps(entries), encoding="utf-8")
        result = _payload(mcp_server.list_forge_log(str(log)))
        assert result["count"] == 2
        assert result["entries"][0]["task_id"] == "a"

    def test_reads_dict_log(self, tmp_path: Path) -> None:
        log = tmp_path / "forge_log.json"
        log.write_text(
            json.dumps({"entries": [{"task_id": "x", "status": "success"}]}),
            encoding="utf-8",
        )
        result = _payload(mcp_server.list_forge_log(str(log)))
        assert result["count"] == 1
        assert result["entries"][0]["task_id"] == "x"

    def test_invalid_json_returns_error(self, tmp_path: Path) -> None:
        log = tmp_path / "forge_log.json"
        log.write_text("not json", encoding="utf-8")
        result = _payload(mcp_server.list_forge_log(str(log)))
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# send_latent_message
# ---------------------------------------------------------------------------


class TestSendLatentMessage:
    def test_requires_feature_flag(self) -> None:
        result = _payload(mcp_server.send_latent_message('{"action":"generate"}'))
        assert result["status"] == "error"
        assert "ENABLE_LATENT_PROTOCOL" in result["error"]

    def test_invalid_json_returns_error(self, monkeypatch) -> None:
        monkeypatch.setenv("ENABLE_LATENT_PROTOCOL", "true")
        result = _payload(mcp_server.send_latent_message("{not json", verify=False))
        assert result["status"] == "error"
        assert "valid JSON" in result["error"]

    def test_encodes_when_enabled_without_verification(self, monkeypatch) -> None:
        monkeypatch.setenv("ENABLE_LATENT_PROTOCOL", "true")
        result = _payload(
            mcp_server.send_latent_message(
                json.dumps({"action": "generate"}),
                context=json.dumps({"domain": "arithmetic"}),
                verify=False,
            )
        )
        assert result["status"] == "ok"
        assert len(result["latent_vector"]) == 16
        assert result["decoded"]["decoded"] is True
        assert result["verification_result"] is None
