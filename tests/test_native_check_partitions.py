"""Native route check-set partition contracts."""

import pytest

pytest.importorskip("agent.native_object_accept")

from agent.core_evidence import (  # noqa: E402
    MACHINE_TV_ASSUMPTION_MARKERS,
    OBJECT_CHECK_VOCABULARY,
    RUNTIME_CHECK_VOCABULARY,
)
from agent.native_machine_tv_recheck import MACHINE_TV_OBJECT_CHECKS  # noqa: E402
from agent.native_object_accept import OBJECT_ACCEPT_CHECKS  # noqa: E402
from agent.native_object_recheck import OBJECT_RECHECK_CHECKS  # noqa: E402

ROUTE_CHECK_SETS = (
    ("machine TV", MACHINE_TV_OBJECT_CHECKS),
    ("object accept", OBJECT_ACCEPT_CHECKS),
    ("object recheck", OBJECT_RECHECK_CHECKS),
)


@pytest.mark.parametrize(("route_name", "checks"), ROUTE_CHECK_SETS)
def test_route_check_sets_exclude_machine_tv_assumptions(
    route_name: str, checks: frozenset[str]
) -> None:
    assert checks.isdisjoint(MACHINE_TV_ASSUMPTION_MARKERS), route_name


@pytest.mark.parametrize(("route_name", "checks"), ROUTE_CHECK_SETS)
def test_route_check_sets_exclude_translation_correspondence(
    route_name: str, checks: frozenset[str]
) -> None:
    assert "object_translation_correspondence" not in checks, route_name


def test_object_recheck_excludes_machine_code_checks() -> None:
    assert not any(
        check.startswith("machine_code_") for check in OBJECT_RECHECK_CHECKS
    )


@pytest.mark.parametrize(("route_name", "checks"), ROUTE_CHECK_SETS)
def test_route_check_sets_exclude_runtime_checks(
    route_name: str, checks: frozenset[str]
) -> None:
    assert checks.isdisjoint(RUNTIME_CHECK_VOCABULARY), route_name


def test_machine_tv_and_accept_route_sets_match_object_vocabulary_partition() -> None:
    expected_checks = (
        OBJECT_CHECK_VOCABULARY
        - {"object_translation_correspondence"}
        - MACHINE_TV_ASSUMPTION_MARKERS
    )
    assert MACHINE_TV_OBJECT_CHECKS == OBJECT_ACCEPT_CHECKS == expected_checks


@pytest.mark.parametrize(("route_name", "checks"), ROUTE_CHECK_SETS)
def test_route_check_sets_are_subsets_of_object_vocabulary(
    route_name: str, checks: frozenset[str]
) -> None:
    assert checks <= OBJECT_CHECK_VOCABULARY, route_name
