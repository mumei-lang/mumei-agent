"""Regression tests for cross-repo harness contract vocabulary.

Covers docs, CLI help text, and MCP docstrings to ensure the
``audit -> migrate-suggest -> heal`` contract and eight fixed keys
are described without aliases across all surfaces.

The doc-only test runs in the lightweight ``contract-vocabulary`` CI job
(pytest-only, no project deps).  Tests that import ``agent.*`` are skipped
when the package is not installed.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_UNDER_CONTRACT = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "docs" / "VERIFICATION_WORKFLOW_GUIDE.md",
    REPO_ROOT / "docs" / "ROADMAP.md",
]
NO_MM_KEYS = [
    "spec_health_issues",
    "verification_violations",
    "verification_status",
    "cross_validation_gaps",
    "next_steps",
    "migration_hints",
    "healed_files",
    "heal_errors",
]
FORBIDDEN_ALIASES = [
    "recommendations",
    "actions",
    "audit_issues",
    "verification_gaps",
    "repair_hints",
    "review_actions",
    "human_review",
]


def _alias_key_patterns(alias: str) -> list[re.Pattern[str]]:
    escaped = re.escape(alias)
    return [
        re.compile(rf"`{escaped}(?:\[\])?`"),
        re.compile(rf'"{escaped}(?:\[\])?"\s*:'),
        re.compile(rf"'{escaped}(?:\[\])?'\s*:"),
        re.compile(rf"(?m)^\s*[-*]?\s*{escaped}(?:\[\])?\s*:"),
        re.compile(rf"\b{escaped}\[\]"),
    ]


def _try_import_audit_schema_keys() -> list[str] | None:
    """Return AUDIT_SCHEMA_KEYS if the agent package is importable, else None."""
    try:
        from agent.audit import AUDIT_SCHEMA_KEYS  # noqa: WPS433
        return AUDIT_SCHEMA_KEYS
    except Exception:
        return None


_needs_agent = pytest.mark.skipif(
    _try_import_audit_schema_keys() is None,
    reason="agent package not installed (lightweight CI)",
)


def test_no_mm_docs_use_fixed_audit_keys_without_alias_keys() -> None:
    failures: list[str] = []
    for path in DOCS_UNDER_CONTRACT:
        text = path.read_text(encoding="utf-8")
        for key in NO_MM_KEYS:
            if key not in text:
                failures.append(f"{path.relative_to(REPO_ROOT)} does not mention `{key}`")
        for alias in FORBIDDEN_ALIASES:
            for pattern in _alias_key_patterns(alias):
                match = pattern.search(text)
                if match:
                    line = text[: match.start()].count("\n") + 1
                    failures.append(
                        f"{path.relative_to(REPO_ROOT)}:{line} documents forbidden alias key `{alias}`"
                    )
                    break
    assert failures == []


@_needs_agent
def test_no_mm_keys_match_audit_schema_keys() -> None:
    """NO_MM_KEYS must equal AUDIT_SCHEMA_KEYS so the test stays in sync."""
    from agent.audit import AUDIT_SCHEMA_KEYS

    assert NO_MM_KEYS == AUDIT_SCHEMA_KEYS


def _get_audit_cli_help() -> str:
    """Build the audit subcommand parser as __main__.py does and return help."""
    import argparse

    from agent.audit import build_parser as audit_build_parser

    parser = argparse.ArgumentParser(
        prog="python -m agent audit",
        description=(
            "Audit existing code by extracting specs, verifying contracts, "
            "emitting cross_validation_gaps, and optionally producing migration_hints."
        ),
    )
    audit_build_parser(parser)
    return parser.format_help()


@_needs_agent
def test_cli_help_uses_fixed_audit_keys_without_alias_keys() -> None:
    """CLI help for audit must mention all 8 fixed keys and no aliases."""
    help_text = _get_audit_cli_help()
    failures: list[str] = []
    for key in NO_MM_KEYS:
        if key not in help_text:
            failures.append(f"audit CLI help does not mention `{key}`")
    for alias in FORBIDDEN_ALIASES:
        for pattern in _alias_key_patterns(alias):
            match = pattern.search(help_text)
            if match:
                failures.append(
                    f"audit CLI help documents forbidden alias key `{alias}`"
                )
                break
    assert failures == [], failures


@_needs_agent
def test_scan_and_fix_docstring_uses_fixed_audit_keys_without_alias_keys() -> None:
    """MCP scan_and_fix docstring must mention all 8 fixed keys and no aliases."""
    from agent.mcp_server import scan_and_fix

    docstring = scan_and_fix.__doc__ or ""
    failures: list[str] = []
    for key in NO_MM_KEYS:
        if key not in docstring:
            failures.append(f"scan_and_fix docstring does not mention `{key}`")
    for alias in FORBIDDEN_ALIASES:
        for pattern in _alias_key_patterns(alias):
            match = pattern.search(docstring)
            if match:
                failures.append(
                    f"scan_and_fix docstring documents forbidden alias key `{alias}`"
                )
                break
    assert failures == [], failures


@_needs_agent
def test_mcp_server_doc_table_matches_registered_tools() -> None:
    """docs/MCP_SERVER.md tool table must list exactly the registered MCP tools."""
    from agent import mcp_server

    mcp_server_doc = REPO_ROOT / "docs" / "MCP_SERVER.md"
    text = mcp_server_doc.read_text(encoding="utf-8")
    table_match = re.search(
        r"Exported tools:\n\n\| Tool \| Arguments \| Documented return keys \|\n"
        r"\|\s*[-—]+\s*\|\s*[-—]+\s*\|\s*[-—]+\s*\|\n"
        r"(.*?)(?:\n\n|\Z)",
        text,
        re.DOTALL,
    )
    assert table_match, "Could not find MCP tools table in docs/MCP_SERVER.md"
    table_body = table_match.group(1)
    doc_tool_names = set(re.findall(r"^\|\s*`(\w+)`\s*\|", table_body, re.MULTILINE))
    registered_names = set(mcp_server.mcp._tool_manager._tools.keys())

    missing_in_docs = registered_names - doc_tool_names
    missing_in_code = doc_tool_names - registered_names
    failures: list[str] = []
    if missing_in_docs:
        failures.append(
            f"registered MCP tools missing from docs/MCP_SERVER.md: {sorted(missing_in_docs)}"
        )
    if missing_in_code:
        failures.append(
            f"docs/MCP_SERVER.md mentions tools not registered: {sorted(missing_in_code)}"
        )
    assert failures == [], "; ".join(failures)


@_needs_agent
def test_mcp_tool_docstrings_do_not_use_forbidden_aliases() -> None:
    """All @mcp.tool() docstrings must avoid forbidden contract vocabulary aliases."""
    from agent import mcp_server

    failures: list[str] = []
    for tool_name, tool in mcp_server.mcp._tool_manager._tools.items():
        docstring = tool.fn.__doc__ or ""
        for alias in FORBIDDEN_ALIASES:
            for pattern in _alias_key_patterns(alias):
                match = pattern.search(docstring)
                if match:
                    line = docstring[: match.start()].count("\n") + 1
                    failures.append(
                        f"{tool_name} docstring line {line} uses forbidden alias `{alias}`"
                    )
                    break
    assert failures == [], "; ".join(failures)


def test_mcp_server_doc_table_avoids_forbidden_aliases() -> None:
    """The docs/MCP_SERVER.md contract table must not use forbidden aliases."""
    mcp_server_doc = REPO_ROOT / "docs" / "MCP_SERVER.md"
    text = mcp_server_doc.read_text(encoding="utf-8")
    table_match = re.search(
        r"Exported tools:\n\n\| Tool \| Arguments \| Documented return keys \|\n"
        r"\|\s*[-—]+\s*\|\s*[-—]+\s*\|\s*[-—]+\s*\|\n"
        r"(.*?)(?:\n\n|\Z)",
        text,
        re.DOTALL,
    )
    assert table_match, "Could not find MCP tools table in docs/MCP_SERVER.md"
    table_body = table_match.group(1)

    failures: list[str] = []
    for line in table_body.splitlines():
        cells = [c.strip() for c in line.replace(r"\|", "§").split("|")]
        if len(cells) < 3:
            continue
        tool_cell = cells[1].strip("`")
        description = " | ".join(cells[1:])
        for alias in FORBIDDEN_ALIASES:
            for pattern in _alias_key_patterns(alias):
                match = pattern.search(description)
                if match:
                    failures.append(
                        f"{tool_cell} description uses forbidden alias `{alias}`"
                    )
                    break
    assert failures == [], "; ".join(failures)
