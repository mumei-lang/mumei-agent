from __future__ import annotations

import json
import sys

import pytest

from agent.config import AgentConfig
from agent.config_report import build_parser, main as config_main
from agent.env_reference import ENV_VARS


def _scrub_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in ENV_VARS:
        monkeypatch.delenv(variable.name, raising=False)
    monkeypatch.delenv("MUMEI_AGENT_PRESET", raising=False)


def _run(monkeypatch: pytest.MonkeyPatch, capsys, *args: str) -> tuple[int, str, str]:
    _scrub_environment(monkeypatch)
    parsed = build_parser().parse_args(args)
    status = config_main(parsed)
    captured = capsys.readouterr()
    return status, captured.out, captured.err


def _entry(report: dict, name: str) -> dict:
    return next(entry for entry in report["env"] if entry["name"] == name)


def test_no_environment_hides_default_entries(monkeypatch, capsys) -> None:
    status, output, _ = _run(monkeypatch, capsys)
    assert status == 0
    assert "environment (0 from env, 0 from preset," in output
    assert "  CONTROLS_GATE =" not in output


def test_all_lists_every_registry_entry_as_default(monkeypatch, capsys) -> None:
    status, output, _ = _run(monkeypatch, capsys, "--all")
    assert status == 0
    assert sum(f"  {entry.name} =" in output for entry in ENV_VARS) == len(ENV_VARS)
    assert output.count("[default]") == len(ENV_VARS)


def test_explicit_environment_value_is_reported_as_env(monkeypatch, capsys) -> None:
    _scrub_environment(monkeypatch)
    monkeypatch.setenv("CONTROLS_GATE", "off")
    args = build_parser().parse_args([])
    assert config_main(args) == 0
    output = capsys.readouterr().out
    assert "CONTROLS_GATE = off  [env]" in output


def test_ci_strict_reports_preset_effective_controls_gate(monkeypatch, capsys) -> None:
    _scrub_environment(monkeypatch)
    monkeypatch.setenv("MUMEI_AGENT_PRESET", "ci-strict")
    args = build_parser().parse_args([])
    assert config_main(args) == 0
    output = capsys.readouterr().out
    assert "preset: ci-strict" in output
    assert "CONTROLS_GATE = require  [preset ci-strict]" in output


def test_explicit_false_overrides_experimental_preset(monkeypatch, capsys) -> None:
    _scrub_environment(monkeypatch)
    monkeypatch.setenv("MUMEI_AGENT_PRESET", "experimental")
    monkeypatch.setenv("ENABLE_LATENT_DEBUG", "false")
    args = build_parser().parse_args([])
    assert config_main(args) == 0
    output = capsys.readouterr().out
    assert "ENABLE_LATENT_DEBUG = false  [env]" in output


def test_experimental_lean_proof_reports_effective_config_field(
    monkeypatch, capsys
) -> None:
    _scrub_environment(monkeypatch)
    monkeypatch.setenv("MUMEI_AGENT_PRESET", "experimental")
    config = AgentConfig()
    args = build_parser().parse_args([])
    assert config_main(args) == 0
    output = capsys.readouterr().out
    expected = "true" if config.enable_lean_ai_proof else "false"
    assert f"ENABLE_LEAN_AI_PROOF = {expected}  [preset experimental]" in output


def test_llm_profile_is_in_header(monkeypatch, capsys) -> None:
    _scrub_environment(monkeypatch)
    monkeypatch.setenv("MUMEI_LLM_PROFILE", "local-small")
    args = build_parser().parse_args([])
    assert config_main(args) == 0
    assert "llm profile: local-small" in capsys.readouterr().out


@pytest.mark.parametrize("all_values", [False, True])
def test_api_key_is_redacted_in_text(monkeypatch, capsys, all_values) -> None:
    _scrub_environment(monkeypatch)
    monkeypatch.setenv("LLM_API_KEY", "sensitive-api-key")
    args = build_parser().parse_args(["--all"] if all_values else [])
    assert config_main(args) == 0
    output = capsys.readouterr().out
    assert "sensitive-api-key" not in output
    assert "LLM_API_KEY = ***" in output


@pytest.mark.parametrize("all_values", [False, True])
def test_json_schema_native_types_and_api_key_redaction(
    monkeypatch, capsys, all_values
) -> None:
    _scrub_environment(monkeypatch)
    monkeypatch.setenv("MUMEI_AGENT_PRESET", "ci-strict")
    monkeypatch.setenv("LLM_API_KEY", "sensitive-api-key")
    args = build_parser().parse_args(["--json", *(["--all"] if all_values else [])])
    assert config_main(args) == 0
    output = capsys.readouterr().out
    assert "sensitive-api-key" not in output
    report = json.loads(output)
    assert set(report) == {"agent_preset", "llm_profile", "env"}
    assert report["agent_preset"] == "ci-strict"
    entry = _entry(report, "ENABLE_LATENT_DEBUG")
    assert entry["category"] == next(
        variable.category for variable in ENV_VARS if variable.name == entry["name"]
    )
    assert entry["source"] == "preset"
    assert entry["set"] is False
    assert entry["effective"] is False
    key_entry = _entry(report, "LLM_API_KEY")
    assert key_entry["value"] == "***"
    assert key_entry["effective"] == "***"
    if not all_values:
        assert all(entry["source"] != "default" for entry in report["env"])


def test_json_all_includes_unset_entries_as_null(monkeypatch, capsys) -> None:
    status, output, _ = _run(monkeypatch, capsys, "--json", "--all")
    assert status == 0
    report = json.loads(output)
    assert len(report["env"]) == len(ENV_VARS)
    entry = _entry(report, "MUMEI_LLM_PROFILE")
    assert entry["set"] is False
    assert entry["value"] is None


def test_unknown_preset_exits_two_with_choices(monkeypatch, capsys) -> None:
    _scrub_environment(monkeypatch)
    monkeypatch.setenv("MUMEI_AGENT_PRESET", "unknown")
    with pytest.raises(ValueError, match="ci-strict.*experimental"):
        AgentConfig()
    args = build_parser().parse_args([])
    assert config_main(args) == 2
    assert "ci-strict" in capsys.readouterr().err


def test_dispatch_config_command(monkeypatch, capsys) -> None:
    _scrub_environment(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["agent", "config"])
    from agent.__main__ import main

    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    assert "preset: none" in capsys.readouterr().out


def test_unregistered_environment_variables_are_not_reported(
    monkeypatch, capsys
) -> None:
    _scrub_environment(monkeypatch)
    monkeypatch.setenv("MUMEI_UNREGISTERED_SECRET", "hidden")
    args = build_parser().parse_args(["--all"])
    assert config_main(args) == 0
    output = capsys.readouterr().out
    assert "MUMEI_UNREGISTERED_SECRET" not in output
    assert "hidden" not in output


def test_generated_cli_reference_contains_config() -> None:
    from pathlib import Path

    reference = Path("docs/CLI_REFERENCE.md").read_text(encoding="utf-8")
    assert "## `mumei-agent config`" in reference
