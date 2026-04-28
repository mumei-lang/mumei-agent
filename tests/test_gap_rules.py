"""Unit tests for ``agent.gap_rules`` and the ``PREFER_MCP_GAPS`` opt-in (P10).

These tests cover three things:

1. The extracted ``analyze_gaps_local`` matches the legacy in-file
   analyzer for representative inputs (so the refactor is a no-op).
2. ``proliferate.analyze_gaps`` delegates to the MCP path when
   ``PREFER_MCP_GAPS=true`` and the mumei module is importable.
3. The MCP path falls back to local analysis when the import fails.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

from agent import gap_rules, proliferate


def _write_mm(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# gap_rules.analyze_gaps_local
# ---------------------------------------------------------------------------


class TestAnalyzeGapsLocal:
    def test_empty_std_returns_default_proposals(self, tmp_path: Path) -> None:
        std = tmp_path / "std"
        std.mkdir()
        result = gap_rules.analyze_gaps_local(std)
        assert result["dependency_graph"] == {}
        assert result["trusted_atoms"] == []
        assert result["todo_comments"] == []
        # The std/core.mm rule fires unconditionally on missing core.
        assert any(p["name"] == "std/core.mm" for p in result["proposals"])

    def test_nonexistent_dir_returns_empty(self, tmp_path: Path) -> None:
        result = gap_rules.analyze_gaps_local(tmp_path / "nope")
        assert result["proposals"] == []

    def test_dependency_graph_captures_imports(self, tmp_path: Path) -> None:
        std = tmp_path / "std"
        _write_mm(
            std / "prelude.mm",
            "atom prelude_ok(x: i64) ensures: true; body: x;\n",
        )
        _write_mm(
            std / "iter.mm",
            'import "std/prelude" as prelude;\n'
            "atom iter_ok(x: i64) ensures: true; body: x;\n",
        )
        result = gap_rules.analyze_gaps_local(std)
        assert "std/prelude.mm" in result["dependency_graph"]["std/iter.mm"]

    def test_re_exports_are_aliases(self) -> None:
        # ``proliferate`` re-exports the names so legacy callers keep
        # working without importing gap_rules directly.
        assert proliferate._STD_GAP_RULES is gap_rules._STD_GAP_RULES
        assert proliferate._scan_std_imports is gap_rules._scan_std_imports
        assert proliferate._evaluate_rule is gap_rules._evaluate_rule


# ---------------------------------------------------------------------------
# proliferate.analyze_gaps with PREFER_MCP_GAPS
# ---------------------------------------------------------------------------


class TestPreferMcpGaps:
    def test_default_uses_local_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PREFER_MCP_GAPS", raising=False)
        std = tmp_path / "std"
        std.mkdir()
        with patch("agent.propose._load_gaps_from_mcp") as mock_mcp:
            result = proliferate.analyze_gaps(std)
        # Local path returns at least the std/core.mm proposal and never
        # touches the MCP loader.
        mock_mcp.assert_not_called()
        assert any(p["name"] == "std/core.mm" for p in result["proposals"])

    def test_prefer_mcp_delegates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PREFER_MCP_GAPS", "true")
        std = tmp_path / "std"
        std.mkdir()
        sentinel = {
            "dependency_graph": {"std/sentinel.mm": []},
            "trusted_atoms": [],
            "todo_comments": [],
            "proposals": [
                {
                    "name": "std/sentinel.mm",
                    "reason": "from MCP",
                    "depends_on": [],
                    "difficulty": "low",
                    "priority": 1,
                }
            ],
        }
        with patch(
            "agent.propose._load_gaps_from_mcp", return_value=sentinel
        ) as mock_mcp:
            result = proliferate.analyze_gaps(std)
        mock_mcp.assert_called_once()
        # The MCP-sourced payload should be passed through unchanged.
        assert result is sentinel

    def test_mcp_unavailable_falls_back(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PREFER_MCP_GAPS", "1")
        std = tmp_path / "std"
        std.mkdir()
        with patch(
            "agent.propose._load_gaps_from_mcp",
            side_effect=SystemExit("mumei not on PYTHONPATH"),
        ):
            result = proliferate.analyze_gaps(std)
        # Should silently fall through to the local analyzer.
        assert any(p["name"] == "std/core.mm" for p in result["proposals"])

    def test_prefer_mcp_off_value_uses_local(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PREFER_MCP_GAPS", "false")
        std = tmp_path / "std"
        std.mkdir()
        with patch("agent.propose._load_gaps_from_mcp") as mock_mcp:
            result = proliferate.analyze_gaps(std)
        mock_mcp.assert_not_called()
        assert isinstance(result["proposals"], list)


# ---------------------------------------------------------------------------
# Smoke test against a fake in-process mcp_server module
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_mcp_server(monkeypatch: pytest.MonkeyPatch):
    """Inject a fake ``mcp_server`` module so MCP delegation is exercised."""
    payload = {
        "dependency_graph": {"std/fake.mm": []},
        "trusted_atoms": [],
        "todo_comments": [],
        "proposals": [
            {
                "name": "std/fake.mm",
                "reason": "from fake MCP",
                "depends_on": [],
                "difficulty": "low",
                "priority": 1,
                "score": 9.99,
            }
        ],
    }
    fake = types.ModuleType("mcp_server")

    def analyze_std_gaps() -> str:
        return json.dumps(payload)

    fake.analyze_std_gaps = analyze_std_gaps
    monkeypatch.setitem(sys.modules, "mcp_server", fake)
    return payload


def test_prefer_mcp_with_fake_module(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_mcp_server: dict,
) -> None:
    monkeypatch.setenv("PREFER_MCP_GAPS", "true")
    std = tmp_path / "std"
    std.mkdir()
    result = proliferate.analyze_gaps(std)
    assert result["proposals"][0]["name"] == "std/fake.mm"
    assert result["proposals"][0]["score"] == 9.99
