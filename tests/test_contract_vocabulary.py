"""Regression tests for cross-repo harness vocabulary and bridge constants.

Covers docs, CLI help text, and MCP docstrings to ensure the
``audit -> migrate-suggest -> heal`` contract and eight fixed keys
are described without aliases across all surfaces. The bridge constants are
checked with stdlib-only catalog and AST parsing so lightweight CI needs no
``agent`` imports.

The doc-only test runs in the lightweight ``contract-vocabulary`` CI job
(pytest-only, no project deps).  Tests that import ``agent.*`` are skipped
when the package is not installed.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_bridge_catalog() -> dict:
    return json.loads(
        (REPO_ROOT / "schema" / "bridge_lemma_catalog.json").read_text(
            encoding="utf-8"
        )
    )


def _bridge_hash(obligation_classes: dict[str, list[str]]) -> str:
    canonical = "\n".join(
        f"{obligation_class}:{lemma}"
        for obligation_class in sorted(obligation_classes)
        for lemma in sorted(obligation_classes[obligation_class])
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _extract_guard_trace_constants() -> dict[str, str]:
    path = REPO_ROOT / "agent" / "strategies" / "foreign_code_strategy_helpers.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if (
                isinstance(target, ast.Name)
                and target.id
                in {
                    "_SOLIDITY_GUARD_TRACE_TRANSLATOR_VERSION",
                    "_SOLIDITY_GUARD_TRACE_BRIDGE_LEMMA_HASH",
                }
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                values[target.id] = node.value.value
    return values


def test_bridge_constants_match_catalog() -> None:
    catalog = _load_bridge_catalog()
    values = _extract_guard_trace_constants()
    assert values["_SOLIDITY_GUARD_TRACE_TRANSLATOR_VERSION"] == catalog[
        "translator_version"
    ]
    assert values["_SOLIDITY_GUARD_TRACE_BRIDGE_LEMMA_HASH"] == _bridge_hash(
        catalog["obligation_classes"]
    )
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
    "trusted_atoms",
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
        r"Exported tools:\n\n\| Tool \| Description \|\n\|[-—]+\|[-—]+\|\n(.*?)(?:\n\n|\Z)",
        text,
        re.DOTALL,
    )
    assert table_match, "Could not find MCP tools table in docs/MCP_SERVER.md"
    table_body = table_match.group(1)
    doc_tool_names = set(re.findall(r"^\|\s*`(\w+)\s*\(", table_body, re.MULTILINE))
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


def test_mcp_server_doc_table_descriptions_avoid_forbidden_aliases() -> None:
    """The docs/MCP_SERVER.md tool table description column must not use forbidden aliases."""
    mcp_server_doc = REPO_ROOT / "docs" / "MCP_SERVER.md"
    text = mcp_server_doc.read_text(encoding="utf-8")
    table_match = re.search(
        r"Exported tools:\n\n\| Tool \| Description \|\n\|[-—]+\|[-—]+\|\n(.*?)(?:\n\n|\Z)",
        text,
        re.DOTALL,
    )
    assert table_match, "Could not find MCP tools table in docs/MCP_SERVER.md"
    table_body = table_match.group(1)

    failures: list[str] = []
    for line in table_body.splitlines():
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 3:
            continue
        tool_cell = cells[1].strip("`")
        description = cells[2]
        for alias in FORBIDDEN_ALIASES:
            for pattern in _alias_key_patterns(alias):
                match = pattern.search(description)
                if match:
                    failures.append(
                        f"{tool_cell} description uses forbidden alias `{alias}`"
                    )
                    break
    assert failures == [], "; ".join(failures)


NATIVE_CHECK_VOCABULARY_NAMES = {
    "OBJECT_CHECK_VOCABULARY",
    "RUNTIME_CHECK_VOCABULARY",
    "MACHINE_TV_ASSUMPTION_MARKERS",
}
NATIVE_CHECK_NAME_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(machine_code_[a-z0-9_]+|os_(?:exit_status|stdout|stderr)_[a-z_]+)"
    r"(?![A-Za-z0-9_])"
)


def _frozenset_constants(path: Path, names: set[str]) -> dict[str, set[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    requested_names = set(names)
    values: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        value = node.value
        if (
            not isinstance(target, ast.Name)
            or target.id not in requested_names
            or not isinstance(value, ast.Call)
            or not isinstance(value.func, ast.Name)
            or value.func.id != "frozenset"
            or len(value.args) != 1
            or value.keywords
        ):
            continue
        try:
            constant = ast.literal_eval(value.args[0])
        except (TypeError, ValueError):
            continue
        if isinstance(constant, (set, frozenset)) and all(
            isinstance(item, str) for item in constant
        ):
            values[target.id] = set(constant)
    return values


@pytest.fixture(scope="module")
def native_check_vocabularies() -> dict[str, set[str]]:
    values = _frozenset_constants(
        REPO_ROOT / "agent" / "core_evidence.py",
        NATIVE_CHECK_VOCABULARY_NAMES,
    )
    assert set(values) == NATIVE_CHECK_VOCABULARY_NAMES
    assert all(values[name] for name in NATIVE_CHECK_VOCABULARY_NAMES)
    return values


def test_machine_tv_assumption_markers_are_object_vocabulary(
    native_check_vocabularies: dict[str, set[str]],
) -> None:
    object_checks = native_check_vocabularies["OBJECT_CHECK_VOCABULARY"]
    runtime_checks = native_check_vocabularies["RUNTIME_CHECK_VOCABULARY"]
    assumption_markers = native_check_vocabularies["MACHINE_TV_ASSUMPTION_MARKERS"]

    assert assumption_markers <= object_checks
    assert object_checks.isdisjoint(runtime_checks)


def test_documented_machine_code_check_names_are_known(
    native_check_vocabularies: dict[str, set[str]],
) -> None:
    allowed_names = (
        native_check_vocabularies["OBJECT_CHECK_VOCABULARY"]
        | native_check_vocabularies["RUNTIME_CHECK_VOCABULARY"]
    )
    paths = {
        *REPO_ROOT.glob("docs/*.md"),
        REPO_ROOT / "README.md",
        REPO_ROOT / "agent" / "mcp_server.py",
        REPO_ROOT / "agent" / "__main__.py",
        *REPO_ROOT.glob("agent/native_*.py"),
    }
    unknown_files: dict[str, set[str]] = {}
    for path in sorted(paths):
        text = path.read_text(encoding="utf-8")
        for match in NATIVE_CHECK_NAME_PATTERN.finditer(text):
            name = match.group(0)
            if name not in allowed_names:
                unknown_files.setdefault(name, set()).add(
                    str(path.relative_to(REPO_ROOT))
                )

    failures = [
        f"{name}: {', '.join(sorted(files))}"
        for name, files in sorted(unknown_files.items())
    ]
    assert failures == [], "Unknown native check names:\n" + "\n".join(failures)


def test_mcp_server_doc_names_every_object_and_runtime_check(
    native_check_vocabularies: dict[str, set[str]],
) -> None:
    documented_names = (
        native_check_vocabularies["OBJECT_CHECK_VOCABULARY"]
        | native_check_vocabularies["RUNTIME_CHECK_VOCABULARY"]
    )
    text = (REPO_ROOT / "docs" / "MCP_SERVER.md").read_text(encoding="utf-8")
    missing = sorted(name for name in documented_names if name not in text)

    assert missing == []


def test_native_surfaces_avoid_overclaim_labels() -> None:
    paths = {
        *REPO_ROOT.glob("agent/native_*.py"),
        REPO_ROOT / "agent" / "mcp_server.py",
        REPO_ROOT / "docs" / "MCP_SERVER.md",
        REPO_ROOT / "docs" / "CLI_REFERENCE.md",
        REPO_ROOT / "docs" / "DESIGN_OBJECT_TV_CONSUMPTION.md",
    }
    forbidden_labels = ("TRUSTLESS", "Correct code proven")
    violations = [
        f"{path.relative_to(REPO_ROOT)} contains {label!r}"
        for path in sorted(paths)
        for label in forbidden_labels
        if label in path.read_text(encoding="utf-8")
    ]

    assert violations == []
