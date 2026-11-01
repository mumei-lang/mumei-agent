from __future__ import annotations

import argparse
import importlib
import os
import subprocess
import sys
from pathlib import Path

from agent.cli_reference import (
    REPO_ROOT,
    _neutralized_environment,
    capture_command_references,
    capture_parser,
    discover_subcommands,
    markdown_cell,
    render_cli_reference,
    render_env_reference,
    render_references,
    sync_reference_docs,
    _default_label,
    _help_text,
    _value_label,
    _visible_actions,
)
from agent.env_reference import (
    ENV_VARS,
    referenced_environment_names,
    scan_environment_names,
    scan_environment_source,
)


def test_generated_documents_are_current_and_check_detects_tampering(tmp_path: Path) -> None:
    docs = REPO_ROOT / "docs"
    assert sync_reference_docs(docs, check=True) == []
    assert (docs / "CLI_REFERENCE.md").read_text(encoding="utf-8") == render_cli_reference()
    assert (docs / "ENV_REFERENCE.md").read_text(encoding="utf-8") == render_env_reference()
    current_check = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "gen_reference_docs.py"),
            "--check",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert current_check.returncode == 0, current_check.stderr

    for name, content in render_references().items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    assert sync_reference_docs(tmp_path, check=True) == []
    (tmp_path / "CLI_REFERENCE.md").write_text("stale\n", encoding="utf-8")
    assert sync_reference_docs(tmp_path, check=True) == ["CLI_REFERENCE.md"]

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "gen_reference_docs.py"),
            "--check",
            "--output-dir",
            str(tmp_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "CLI_REFERENCE.md" in result.stderr


def test_reference_rendering_ignores_polluted_environment_and_dotenv(
    tmp_path: Path, monkeypatch
) -> None:
    expected = render_references()
    monkeypatch.setenv("CONTROLS_GATE", "require")
    monkeypatch.setenv("AGENT_STRATEGY", "multi-stage")
    monkeypatch.setenv("LLM_MODEL", "environment-model")
    monkeypatch.setenv("ENABLE_CHARTER_GUARD", "false")
    monkeypatch.setenv("MUMEI_LLM_PROFILE", "local-large")
    (tmp_path / ".env").write_text(
        "CONTROLS_GATE=off\nAGENT_STRATEGY=from-dotenv\nLLM_MODEL=dotenv-model\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    assert render_references() == expected
    assert os.environ["CONTROLS_GATE"] == "require"


def test_env_registry_covers_reads_without_stale_or_duplicate_entries() -> None:
    names = [entry.name for entry in ENV_VARS]
    assert len(names) == len(set(names))
    registered = set(names)
    generic_platform_names = {"HOME", "PATH"}
    assert scan_environment_names(REPO_ROOT) - registered <= generic_platform_names
    assert registered <= referenced_environment_names(REPO_ROOT)
    assert all(entry.category for entry in ENV_VARS)
    assert all(entry.kind in {"toggle", "value"} for entry in ENV_VARS)
    toggles = [entry for entry in ENV_VARS if entry.name.startswith("ENABLE_")]
    assert len(toggles) == 16
    assert sum(entry.default.lower() == "true" for entry in toggles) == 9
    assert sum(entry.default.lower() == "false" for entry in toggles) == 7


def test_environment_scanner_handles_literal_read_forms_and_comments() -> None:
    source = """
    os.getenv(
        "ONE",
        "fallback",
    )
    os.environ . get ( "TWO" )
    os.environ["THREE"]
    "FOUR" in os.environ
    os.environ.setdefault("FIVE", "")
    _env_bool(
        "SIX",
        True,
    )
    # os.getenv("COMMENTED") is counted conservatively.
    """
    assert scan_environment_source(source) == {
        "ONE",
        "TWO",
        "THREE",
        "FOUR",
        "FIVE",
        "SIX",
        "COMMENTED",
    }
    assert scan_environment_source('export FOO="${FROM_SHELL:-value}"', ".sh") == {
        "FROM_SHELL"
    }


def test_registry_defaults_match_agent_config_when_environment_is_scrubbed() -> None:
    with _neutralized_environment():
        config_module = importlib.import_module("agent.config")
        config = config_module.AgentConfig()

    for entry in ENV_VARS:
        if entry.config_field is None:
            continue
        actual = getattr(config, entry.config_field)
        if entry.name == "CORE_AXIOM_PATH":
            assert isinstance(actual, str) and actual
        elif actual is None:
            assert entry.default == ""
        elif isinstance(actual, bool):
            assert (entry.default.lower() == "true") is actual
        elif isinstance(actual, int):
            assert int(entry.default) == actual
        elif isinstance(actual, float):
            assert float(entry.default) == actual
        else:
            assert entry.default == str(actual)


def test_ast_subcommands_and_visible_parser_option_counts_are_documented() -> None:
    commands = discover_subcommands()
    assert len(commands) == 25
    document = render_cli_reference()
    references = capture_command_references()
    assert [reference.name for reference in references] == commands
    for reference in references:
        assert f"## `mumei-agent {reference.name}`" in document
        overview_row = next(
            line for line in document.splitlines() if line.startswith(f"| `{reference.name}` |")
        )
        assert f"| {len(reference.options)} |" in overview_row
        assert all(action.help != argparse.SUPPRESS for action in reference.options)
    mcp_server = next(reference for reference in references if reference.name == "mcp-server")
    assert mcp_server.options == []
    assert "extra arguments are ignored" in mcp_server.description
    assert (
        "| `--controls-gate` | {off, warn, require} | — | "
        "Negative-controls gate mode (default: CONTROLS_GATE or warn) |"
    ) in document
    assert "Rank verified heal candidates using negative controls (default: off)." in document


def test_parser_capture_restores_argparse_and_argv_on_success_and_error() -> None:
    original_parse_args = argparse.ArgumentParser.parse_args
    original_parse_known_args = argparse.ArgumentParser.parse_known_args
    original_argv = sys.argv

    def parse_command() -> None:
        parser = argparse.ArgumentParser()
        parser.add_argument("--value")
        parser.parse_args()

    parser = capture_parser(parse_command, ["fixture", "command"])
    assert parser is not None
    assert argparse.ArgumentParser.parse_args is original_parse_args
    assert argparse.ArgumentParser.parse_known_args is original_parse_known_args
    assert sys.argv is original_argv

    def fail_before_parse() -> None:
        raise RuntimeError("capture failure")

    try:
        capture_parser(fail_before_parse, ["fixture", "command"])
    except RuntimeError as error:
        assert str(error) == "capture failure"
    else:
        raise AssertionError("capture helper swallowed a command exception")
    assert argparse.ArgumentParser.parse_args is original_parse_args
    assert argparse.ArgumentParser.parse_known_args is original_parse_known_args
    assert sys.argv is original_argv


def test_markdown_cells_escape_pipes_and_collapse_whitespace() -> None:
    assert markdown_cell(" first | second\n third ") == r"first \| second third"
    assert markdown_cell(None) == "—"
    assert markdown_cell(" \n ") == "—"


def test_hidden_actions_boolean_defaults_choices_and_help_expansion() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--enabled", action="store_true", help="Enable the feature.")
    parser.add_argument(
        "--mode",
        choices=["fast", "safe"],
        default="safe",
        help="Choose %(default)s from %(choices)s.",
    )
    parser.add_argument("--hidden", help=argparse.SUPPRESS)
    options = _visible_actions(parser, positional=False)
    assert [action.dest for action in options] == ["enabled", "mode"]
    assert _default_label(options[0]) == "—"
    assert _value_label(options[1]) == "{fast, safe}"
    assert _default_label(options[1]) == "safe"
    assert _help_text(parser, options[1]) == "Choose safe from fast, safe."
