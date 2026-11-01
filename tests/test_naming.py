from __future__ import annotations

import argparse
import re
from collections.abc import Iterable, Mapping

from agent.cli_reference import capture_command_references
from agent.env_reference import ENV_VARS

DEFAULT_GRANDFATHER_REASON = (
    "pre-convention name; renaming needs an alias and a deprecation window "
    "(see docs/NAMING.md)"
)

GRANDFATHERED = {
    ("mumei-agent validate-code --no-llm", "F3"): DEFAULT_GRANDFATHER_REASON,
    ("mumei-agent validate-code --no-mumei", "F3"): DEFAULT_GRANDFATHER_REASON,
    ("mumei-agent validate-code-to-spec --no-llm", "F3"): DEFAULT_GRANDFATHER_REASON,
    ("mumei-agent validate-code-to-spec --no-mumei", "F3"): DEFAULT_GRANDFATHER_REASON,
    ("mumei-agent validate-spec --no-llm", "F3"): DEFAULT_GRANDFATHER_REASON,
    ("mumei-agent validate-spec --no-mumei", "F3"): DEFAULT_GRANDFATHER_REASON,
    ("mumei-agent validate-spec-to-code --no-llm", "F3"): DEFAULT_GRANDFATHER_REASON,
    ("mumei-agent validate-spec-to-code --no-mumei", "F3"): DEFAULT_GRANDFATHER_REASON,
    ("mumei-agent verify-conformance --no-llm", "F3"): DEFAULT_GRANDFATHER_REASON,
    ("mumei-agent verify-conformance --no-mumei", "F3"): DEFAULT_GRANDFATHER_REASON,
    ("mumei-agent verify-traceability --no-llm", "F3"): DEFAULT_GRANDFATHER_REASON,
    ("mumei-agent verify-traceability --no-mumei", "F3"): DEFAULT_GRANDFATHER_REASON,
    ("USE_MCP_CLIENT", "E2"): DEFAULT_GRANDFATHER_REASON,
    ("USE_MCP_CLIENT", "E5"): DEFAULT_GRANDFATHER_REASON,
    ("USE_MCP_SAMPLING", "E2"): DEFAULT_GRANDFATHER_REASON,
    ("USE_MCP_SAMPLING", "E5"): DEFAULT_GRANDFATHER_REASON,
    ("CEGIS_ESCALATE_TO_LEAN", "E5"): DEFAULT_GRANDFATHER_REASON,
    ("INJECT_CORE_AXIOMS", "E5"): DEFAULT_GRANDFATHER_REASON,
    ("PREFER_MCP_GAPS", "E5"): DEFAULT_GRANDFATHER_REASON,
}

SAFETY_RELAXATIONS = {
    "--allow-contract-erosion": (
        "Bypasses the default contract-erosion guard that rejects candidate fixes "
        "removing existing contract clauses."
    ),
}

EXTERNAL = {
    "CI_FIXTURE_MODE": "Shared fixture-mode control used by repository CI.",
    "GITHUB_*": "Variables defined by GitHub Actions and GitHub tooling.",
    "OPENAI_API_KEY": "Credential name defined by the OpenAI client ecosystem.",
    "OTEL_*": "Variables defined by the OpenTelemetry SDK and ecosystem.",
    "TRACEPARENT": "W3C distributed trace context variable.",
    "TRACESTATE": "W3C distributed trace state variable.",
    "LD_LIBRARY_PATH": "Dynamic loader variable defined by the operating system.",
    "LLVM_SYS_170_PREFIX": "Installation prefix defined by llvm-sys tooling.",
    "Z3_SYS_*": "Build variables defined by z3-sys tooling.",
}

_LONG_FLAG_PATTERN = re.compile(r"--[a-z0-9]+(-[a-z0-9]+)*\Z")
_ENV_NAME_PATTERN = re.compile(r"[A-Z][A-Z0-9_]*\Z")


def _collect_parser_flags(
    command: str, parser: argparse.ArgumentParser
) -> set[tuple[str, str]]:
    flags = set()
    for action in parser._actions:
        for option in action.option_strings:
            if option.startswith("--") and option not in {"--help", "--version"}:
                flags.add((command, option))
    return flags


def _collect_flags() -> set[tuple[str, str]]:
    flags = set()
    for reference in capture_command_references():
        command = f"mumei-agent {reference.name}"
        flags.update(_collect_parser_flags(command, reference.parser))
    return flags


def _flag_violations(
    flags: Iterable[tuple[str, str]],
    safety_relaxations: Mapping[str, str] = SAFETY_RELAXATIONS,
) -> set[tuple[str, str]]:
    flags = set(flags)
    violations = set()
    for command, flag in flags:
        scoped_name = f"{command} {flag}"
        if not _LONG_FLAG_PATTERN.fullmatch(flag):
            violations.add((scoped_name, "F1"))
        if flag.startswith("--disable-"):
            counterpart = f"--enable-{flag.removeprefix('--disable-')}"
            if (command, counterpart) not in flags:
                violations.add((scoped_name, "F2"))
        if flag.startswith("--no-"):
            counterpart = f"--{flag.removeprefix('--no-')}"
            if (command, counterpart) not in flags:
                violations.add((scoped_name, "F3"))
        if flag.startswith("--allow-") and flag not in safety_relaxations:
            violations.add((scoped_name, "F4"))
        if flag.startswith(("--with-", "--without-", "--skip-", "--use-", "--dont-")):
            violations.add((scoped_name, "F5"))
    return violations


def _is_external(name: str) -> bool:
    for selector in EXTERNAL:
        if selector.endswith("*") and name.startswith(selector[:-1]):
            return True
        if selector == name:
            return True
    return False


def _environment_violations(
    variables: Iterable[tuple[str, str, str]],
    safety_relaxations: Mapping[str, str] = SAFETY_RELAXATIONS,
) -> set[tuple[str, str]]:
    violations = set()
    for name, _category, kind in variables:
        if not _ENV_NAME_PATTERN.fullmatch(name):
            violations.add((name, "E1"))
        if "ALLOW" in name and name not in safety_relaxations:
            violations.add((name, "E4"))
        if _is_external(name):
            continue
        if name.startswith(
            (
                "USE_",
                "DISABLE_",
                "NO_",
                "MUMEI_USE_",
                "MUMEI_DISABLE_",
                "MUMEI_NO_",
            )
        ) or name.endswith(("_ENABLED", "_DISABLED")):
            violations.add((name, "E2"))
        if kind == "toggle" and not name.startswith("ENABLE_"):
            violations.add((name, "E5"))
    return violations


def _all_violations() -> set[tuple[str, str]]:
    flags = _collect_flags()
    variables = [(entry.name, entry.category, entry.kind) for entry in ENV_VARS]
    return _flag_violations(flags) | _environment_violations(variables)


def _assert_violation(
    violations: set[tuple[str, str]], name: str, rule: str
) -> None:
    assert (name, rule) in violations, f"{rule} regression not rejected; see docs/NAMING.md"


def _unrecorded_violations(
    violations: set[tuple[str, str]],
    grandfathered: Mapping[tuple[str, str], str],
) -> set[tuple[str, str]]:
    return violations - set(grandfathered)


def test_existing_violations_are_grandfathered_and_entries_are_not_stale() -> None:
    violations = _all_violations()
    expected = set(GRANDFATHERED)
    unrecorded = _unrecorded_violations(violations, GRANDFATHERED)
    stale = expected - violations
    assert not unrecorded, (
        f"unrecorded naming violations {sorted(violations)}; see docs/NAMING.md"
    )
    assert not stale, (
        f"stale GRANDFATHERED entries for F1-F5/E1-E5: {sorted(stale)}; "
        "see docs/NAMING.md"
    )
    assert all(reason.strip() for reason in GRANDFATHERED.values()), (
        "GRANDFATHERED reasons must be non-empty; see docs/NAMING.md"
    )


def test_safety_relaxations_exist_and_have_reasons() -> None:
    flags = _collect_flags()
    flag_names = {flag for _, flag in flags}
    env_names = {entry.name for entry in ENV_VARS}
    for name, reason in SAFETY_RELAXATIONS.items():
        assert name in flag_names or name in env_names, (
            f"stale safety relaxation {name} (F4/E4); see docs/NAMING.md"
        )
        assert reason.strip(), f"empty safety reason for {name} (F4/E4); see docs/NAMING.md"


def test_flag_rule_regressions_are_rejected_and_compliant_names_are_accepted() -> None:
    flags = {("mumei-agent demo", "--Bad_name")}
    violations = _flag_violations(flags)
    _assert_violation(violations, "mumei-agent demo --Bad_name", "F1")
    assert not _flag_violations({("mumei-agent demo", "--good-name")}), (
        "F1 compliant name rejected; see docs/NAMING.md"
    )

    _assert_violation(
        _flag_violations({("mumei-agent demo", "--disable-cache")}),
        "mumei-agent demo --disable-cache",
        "F2",
    )
    assert not _flag_violations(
        {
            ("mumei-agent demo", "--enable-cache"),
            ("mumei-agent demo", "--disable-cache"),
        }
    ), "F2 compliant pair rejected; see docs/NAMING.md"

    _assert_violation(
        _flag_violations({("mumei-agent demo", "--no-cache")}),
        "mumei-agent demo --no-cache",
        "F3",
    )
    assert not _flag_violations(
        {
            ("mumei-agent demo", "--cache"),
            ("mumei-agent demo", "--no-cache"),
        }
    ), "F3 compliant pair rejected; see docs/NAMING.md"

    _assert_violation(
        _flag_violations({("mumei-agent demo", "--allow-preview")}),
        "mumei-agent demo --allow-preview",
        "F4",
    )
    assert not _flag_violations(
        {("mumei-agent demo", "--allow-contract-erosion")}
    ), "F4 documented safety relaxation rejected; see docs/NAMING.md"

    _assert_violation(
        _flag_violations({("mumei-agent demo", "--use-cache")}),
        "mumei-agent demo --use-cache",
        "F5",
    )
    assert not _flag_violations(
        {("mumei-agent demo", "--enable-cache")}
    ), "F5 compliant name rejected; see docs/NAMING.md"


def test_hidden_parser_options_are_included_in_flag_rule_checks() -> None:
    parser = argparse.ArgumentParser(prog="fixture")
    parser.add_argument("--Bad_Flag", help=argparse.SUPPRESS)
    violations = _flag_violations(_collect_parser_flags("fixture", parser))
    _assert_violation(violations, "fixture --Bad_Flag", "F1")


def test_environment_rule_regressions_are_rejected_and_compliant_names_are_accepted() -> None:
    _assert_violation(
        _environment_violations([("mumei_cache", "features", "value")]),
        "mumei_cache",
        "E1",
    )
    assert not _environment_violations([("MUMEI_CACHE", "features", "value")]), (
        "E1 compliant name rejected; see docs/NAMING.md"
    )

    _assert_violation(
        _environment_violations([("USE_CACHE", "features", "value")]),
        "USE_CACHE",
        "E2",
    )
    _assert_violation(
        _environment_violations([("USE_CI_FEATURE", "ci", "value")]),
        "USE_CI_FEATURE",
        "E2",
    )
    assert not _environment_violations([("ENABLE_CACHE", "features", "toggle")]), (
        "E2 compliant name rejected; see docs/NAMING.md"
    )

    _assert_violation(
        _environment_violations([("CACHE_ACTIVE", "features", "toggle")]),
        "CACHE_ACTIVE",
        "E5",
    )
    assert not _environment_violations([("ENABLE_CACHE", "features", "toggle")]), (
        "E5 compliant toggle rejected; see docs/NAMING.md"
    )

    _assert_violation(
        _environment_violations([("MUMEI_ALLOW_PREVIEW", "features", "value")]),
        "MUMEI_ALLOW_PREVIEW",
        "E4",
    )
    assert not _environment_violations(
        [("MUMEI_ALLOW_PREVIEW", "features", "value")],
        safety_relaxations={"MUMEI_ALLOW_PREVIEW": "test safety check"},
    ), "E4 documented safety relaxation rejected; see docs/NAMING.md"


def test_grandfathering_is_rule_specific() -> None:
    violations = _environment_violations([("USE_CACHE", "mcp", "toggle")])
    grandfathered = {("USE_CACHE", "E2"): "legacy negative toggle"}
    assert _unrecorded_violations(violations, grandfathered) == {("USE_CACHE", "E5")}, (
        "a grandfathered name must still fail for an unrecorded rule; see docs/NAMING.md"
    )
