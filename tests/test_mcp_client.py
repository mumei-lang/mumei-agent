"""Unit tests for ``agent.mcp_client.MumeiMCPClient`` (P10)."""
from __future__ import annotations

import json
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from agent import mcp_client
from agent.mcp_client import MumeiMCPClient, use_mcp_client_enabled
from agent.mumei_client import MumeiClient, create_mumei_client


# ---------------------------------------------------------------------------
# use_mcp_client_enabled
# ---------------------------------------------------------------------------


class TestUseMcpClientEnabled:
    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
    def test_truthy_values(
        self, value: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("USE_MCP_CLIENT", value)
        assert use_mcp_client_enabled() is True

    @pytest.mark.parametrize("value", ["", "0", "false", "no"])
    def test_falsy_values(
        self, value: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("USE_MCP_CLIENT", value)
        assert use_mcp_client_enabled() is False


# ---------------------------------------------------------------------------
# MumeiMCPClient mode detection
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_mcp_module(monkeypatch: pytest.MonkeyPatch):
    """Inject a fake ``mcp_server`` module exposing the standard tools."""
    fake = types.ModuleType("mcp_server")

    def validate_logic(source_code: str) -> str:
        return (
            "Forge succeeded\n"
            "### Verification Report\n"
            "```json\n"
            + json.dumps(
                {
                    "success": True,
                    "semantic_feedback": {"violated_constraints": []},
                    "machine_readable": {"status": "ok"},
                }
            )
            + "\n```\n"
        )

    def analyze_std_gaps() -> str:
        return json.dumps({"proposals": [{"name": "std/foo.mm"}]})

    def list_std_catalog() -> str:
        return json.dumps({"modules": [{"path": "std/foo.mm"}]})

    def get_inferred_effects(source_code: str) -> str:
        return json.dumps({"effects": ["IO"]})

    def visualize_std_graph(format: str = "mermaid") -> str:
        return f"graph {format}"

    fake.validate_logic = validate_logic
    fake.analyze_std_gaps = analyze_std_gaps
    fake.list_std_catalog = list_std_catalog
    fake.get_inferred_effects = get_inferred_effects
    fake.visualize_std_graph = visualize_std_graph

    monkeypatch.setitem(sys.modules, "mcp_server", fake)
    return fake


class TestModeDetection:
    def test_unavailable_when_module_missing_and_no_command(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delitem(sys.modules, "mcp_server", raising=False)
        # Block re-import via importlib.import_module so the constructor
        # cannot find the module on the sys.path either.
        with patch(
            "importlib.import_module",
            side_effect=ImportError("mcp_server"),
        ):
            client = MumeiMCPClient()
        assert client.mode == "unavailable"

    def test_in_process_mode_when_module_present(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_mcp_module: types.ModuleType,
    ) -> None:
        client = MumeiMCPClient()
        assert client.mode == "in-process"

    def test_stdio_mode_when_command_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MUMEI_MCP_COMMAND", "python -m agent mcp-server")
        with patch(
            "importlib.import_module",
            side_effect=ImportError("mcp_server"),
        ):
            client = MumeiMCPClient()
        assert client.mode == "stdio"


# ---------------------------------------------------------------------------
# Tool wrappers
# ---------------------------------------------------------------------------


class TestValidateLogic:
    def test_in_process_returns_structured_payload(
        self, fake_mcp_module: types.ModuleType
    ) -> None:
        client = MumeiMCPClient()
        result = client.validate_logic("atom ok() ensures: true; body: 0;")
        assert result["success"] is True
        assert result["mode"] == "in-process"
        assert result["report"]["machine_readable"]["status"] == "ok"
        assert "violated_constraints" in result["semantic_feedback"]

    def test_falls_back_when_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delitem(sys.modules, "mcp_server", raising=False)
        fallback = MagicMock()
        fallback.verify.return_value = {
            "success": True,
            "report": {"semantic_feedback": {}},
            "stdout": "ok",
            "stderr": "",
        }
        with patch(
            "importlib.import_module",
            side_effect=ImportError("mcp_server"),
        ):
            client = MumeiMCPClient(fallback_client=fallback)
        result = client.validate_logic("atom ok() ensures: true; body: 0;")
        fallback.verify.assert_called_once()
        assert result["mode"] == "fallback"
        assert result["success"] is True

    def test_in_process_failure_falls_back(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_mcp_module: types.ModuleType,
    ) -> None:
        # Force the in-process tool to raise so the fallback path runs.
        def boom(*_a, **_kw):
            raise RuntimeError("validate_logic blew up")

        fake_mcp_module.validate_logic = boom
        fallback = MagicMock()
        fallback.verify.return_value = {
            "success": False,
            "report": {},
            "stdout": "",
            "stderr": "verify failed",
        }
        client = MumeiMCPClient(fallback_client=fallback)
        result = client.validate_logic("atom bad() ensures: false; body: 0;")
        fallback.verify.assert_called_once()
        assert result["mode"] == "fallback"
        assert result["success"] is False


class TestOtherTools:
    def test_analyze_gaps(
        self, fake_mcp_module: types.ModuleType
    ) -> None:
        client = MumeiMCPClient()
        gaps = client.analyze_gaps()
        assert gaps["proposals"][0]["name"] == "std/foo.mm"

    def test_list_catalog(
        self, fake_mcp_module: types.ModuleType
    ) -> None:
        client = MumeiMCPClient()
        catalog = client.list_catalog()
        assert catalog["modules"][0]["path"] == "std/foo.mm"

    def test_get_effects(
        self, fake_mcp_module: types.ModuleType
    ) -> None:
        client = MumeiMCPClient()
        effects = client.get_effects("atom ok() ensures: true; body: 0;")
        assert effects["effects"] == ["IO"]

    def test_visualize_graph(
        self, fake_mcp_module: types.ModuleType
    ) -> None:
        client = MumeiMCPClient()
        graph = client.visualize_graph(format="dot")
        assert graph == "graph dot"

    def test_visualize_graph_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delitem(sys.modules, "mcp_server", raising=False)
        with patch(
            "importlib.import_module",
            side_effect=ImportError("mcp_server"),
        ):
            client = MumeiMCPClient()
        with pytest.raises(RuntimeError):
            client.visualize_graph()


# ---------------------------------------------------------------------------
# create_mumei_client factory
# ---------------------------------------------------------------------------


class TestCreateMumeiClient:
    def test_default_returns_subprocess_client(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("USE_MCP_CLIENT", raising=False)
        client = create_mumei_client("mumei")
        assert isinstance(client, MumeiClient)
        assert not isinstance(client, MumeiMCPClient)

    def test_use_mcp_with_module_returns_mcp_client(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_mcp_module: types.ModuleType,
    ) -> None:
        monkeypatch.setenv("USE_MCP_CLIENT", "true")
        client = create_mumei_client("mumei")
        assert isinstance(client, MumeiMCPClient)

    def test_use_mcp_without_transport_falls_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("USE_MCP_CLIENT", "true")
        monkeypatch.delitem(sys.modules, "mcp_server", raising=False)
        with patch(
            "importlib.import_module",
            side_effect=ImportError("mcp_server"),
        ):
            client = create_mumei_client("mumei")
        assert isinstance(client, MumeiClient)
        assert not isinstance(client, MumeiMCPClient)


# ---------------------------------------------------------------------------
# verify shim — MumeiClient API compat
# ---------------------------------------------------------------------------


class TestVerifyShim:
    def test_verify_uses_validate_logic_when_enabled(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
        fake_mcp_module: types.ModuleType,
    ) -> None:
        monkeypatch.setenv("USE_MCP_CLIENT", "true")
        path = tmp_path / "demo.mm"
        path.write_text("atom ok() ensures: true; body: 0;", encoding="utf-8")
        client = MumeiMCPClient()
        result = client.verify(str(path))
        assert result["success"] is True
        assert result["mcp"] is True

    def test_verify_falls_back_when_disabled(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
        fake_mcp_module: types.ModuleType,
    ) -> None:
        monkeypatch.delenv("USE_MCP_CLIENT", raising=False)
        path = tmp_path / "demo.mm"
        path.write_text("atom ok() ensures: true; body: 0;", encoding="utf-8")
        fallback = MagicMock()
        fallback.verify.return_value = {
            "success": True,
            "report": {},
            "stdout": "",
            "stderr": "",
        }
        client = MumeiMCPClient(fallback_client=fallback)
        client.verify(str(path))
        fallback.verify.assert_called_once()
