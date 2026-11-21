"""Tests for inherited outstanding checks in std dependency closures."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.core_evidence import (
    UNPERFORMED_CHECK_RECOVERY_SCHEMA,
    evaluate_unperformed_check_recovery,
)
from agent.dependency_invalidation import (
    DEPENDENCY_CHECKS_SCHEMA,
    inherit_dependency_checks,
)


def _std(tmp_path: Path, files: dict[str, str]) -> Path:
    std_dir = tmp_path / "std"
    std_dir.mkdir(parents=True, exist_ok=True)
    for rel, body in files.items():
        path = std_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return std_dir


def _report(*checks: str) -> dict[str, object]:
    return {"checks_not_performed": list(checks)}


def test_chain_inherits_transitive_checks(tmp_path: Path) -> None:
    std_dir = _std(
        tmp_path,
        {
            "a.mm": "",
            "b.mm": 'import "std/a";\n',
            "c.mm": 'import "std/b";\n',
        },
    )
    result = inherit_dependency_checks(
        std_dir,
        {
            "std/a.mm": _report("signature_verification"),
            "std/b.mm": {},
            "std/c.mm": {},
        },
    )

    assert result["schema_version"] == DEPENDENCY_CHECKS_SCHEMA
    assert result["files"]["std/b.mm"]["inherited"] == {
        "signature_verification": ["std/a.mm"]
    }
    assert result["files"]["std/c.mm"]["inherited"] == {
        "signature_verification": ["std/a.mm"]
    }


def test_recovery_report_propagates_only_unrecovered_checks(
    tmp_path: Path,
) -> None:
    std_dir = _std(
        tmp_path,
        {"a.mm": "", "b.mm": 'import "std/a";\n'},
    )
    recovery = evaluate_unperformed_check_recovery(
        {"checks_not_performed": ["signature_verification", "freshness"]},
        [
            {
                "schema_version": "mumei.signature-verification/v1",
                "signature_valid": True,
            }
        ],
    )
    assert recovery["schema_version"] == UNPERFORMED_CHECK_RECOVERY_SCHEMA
    assert recovery["recovered"] == ["signature_verification"]
    assert recovery["unrecovered"] == ["freshness"]

    result = inherit_dependency_checks(
        std_dir,
        {"std/a.mm": recovery, "std/b.mm": {}},
    )
    assert result["files"]["std/a.mm"]["own"] == ["freshness"]
    assert result["files"]["std/b.mm"]["inherited"] == {"freshness": ["std/a.mm"]}
    assert (
        "signature_verification"
        not in result["files"]["std/b.mm"]["checks_not_performed"]
    )


def test_recovery_report_without_evidence_propagates_unrecovered(
    tmp_path: Path,
) -> None:
    std_dir = _std(
        tmp_path,
        {"a.mm": "", "b.mm": 'import "std/a";\n'},
    )
    recovery = evaluate_unperformed_check_recovery(
        {"checks_not_performed": ["signature_verification"]}, []
    )
    assert recovery["unrecovered"] == ["signature_verification"]

    result = inherit_dependency_checks(
        std_dir,
        {"std/a.mm": recovery},
    )
    assert result["files"]["std/b.mm"]["inherited"] == {
        "signature_verification": ["std/a.mm"]
    }


def test_hand_made_recovery_report_uses_only_unrecovered(
    tmp_path: Path,
) -> None:
    std_dir = _std(
        tmp_path,
        {"a.mm": "", "b.mm": 'import "std/a";\n'},
    )
    recovery = {
        "schema_version": UNPERFORMED_CHECK_RECOVERY_SCHEMA,
        "recovered": ["discharged"],
        "unrecovered": ["remaining"],
    }
    result = inherit_dependency_checks(std_dir, {"std/a.mm": recovery})

    assert result["files"]["std/a.mm"]["own"] == ["remaining"]
    assert result["files"]["std/b.mm"]["inherited"] == {"remaining": ["std/a.mm"]}


def test_diamond_inherited_sources_are_sorted_and_deduplicated(
    tmp_path: Path,
) -> None:
    std_dir = _std(
        tmp_path,
        {
            "a.mm": "",
            "b.mm": 'import "std/a";\n',
            "c.mm": 'import "std/a";\n',
            "d.mm": 'import "std/c";\nimport "std/b";\n',
        },
    )
    result = inherit_dependency_checks(
        std_dir,
        {
            "std/d.mm": {},
            "std/c.mm": _report("shared"),
            "std/a.mm": _report("shared"),
            "std/b.mm": _report("shared"),
        },
    )

    assert result["files"]["std/d.mm"]["inherited"] == {
        "shared": ["std/a.mm", "std/b.mm", "std/c.mm"]
    }


def test_cycle_terminates_and_does_not_inherit_own_checks(
    tmp_path: Path,
) -> None:
    std_dir = _std(
        tmp_path,
        {
            "a.mm": 'import "std/b";\n',
            "b.mm": 'import "std/a";\n',
        },
    )
    result = inherit_dependency_checks(
        std_dir,
        {
            "std/a.mm": _report("from_a"),
            "std/b.mm": _report("from_b"),
        },
    )

    assert result["files"]["std/a.mm"]["inherited"] == {"from_b": ["std/b.mm"]}
    assert result["files"]["std/b.mm"]["inherited"] == {"from_a": ["std/a.mm"]}


def test_implicit_prelude_checks_reach_every_other_file(
    tmp_path: Path,
) -> None:
    std_dir = _std(
        tmp_path,
        {
            "prelude.mm": "",
            "a.mm": "",
            "nested/b.mm": "",
        },
    )
    result = inherit_dependency_checks(
        std_dir,
        {
            "std/prelude.mm": _report("prelude_check"),
            "std/a.mm": {},
            "std/nested/b.mm": {},
        },
    )

    for key in ("std/a.mm", "std/nested/b.mm"):
        assert result["files"][key]["inherited"] == {
            "prelude_check": ["std/prelude.mm"]
        }
    assert result["files"]["std/prelude.mm"]["inherited"] == {}


def test_missing_dependency_report_adds_verification_marker(
    tmp_path: Path,
) -> None:
    std_dir = _std(
        tmp_path,
        {"a.mm": "", "b.mm": 'import "std/a";\n'},
    )
    result = inherit_dependency_checks(std_dir, {"std/b.mm": {}})

    dependent = result["files"]["std/b.mm"]
    assert dependent["own"] == []
    assert dependent["dependencies_without_report"] == ["std/a.mm"]
    assert dependent["checks_not_performed"] == ["dependency_verification"]


def test_unresolved_import_in_dependency_closure_adds_resolution_marker(
    tmp_path: Path,
) -> None:
    std_dir = _std(
        tmp_path,
        {
            "a.mm": 'import "std/missing";\n',
            "b.mm": 'import "std/a";\n',
        },
    )
    result = inherit_dependency_checks(
        std_dir,
        {"std/a.mm": {}, "std/b.mm": {}},
    )

    assert result["files"]["std/a.mm"]["unresolved_in_closure"] is True
    dependent = result["files"]["std/b.mm"]
    assert dependent["unresolved_in_closure"] is True
    assert dependent["checks_not_performed"] == ["dependency_resolution"]


def test_symlink_alias_dependency_inherits_report(
    tmp_path: Path,
) -> None:
    std_dir = _std(
        tmp_path,
        {
            "a.mm": "",
            "b.mm": 'import "std/alias.mm";\n',
        },
    )
    alias = std_dir / "alias.mm"
    try:
        alias.symlink_to(std_dir / "a.mm")
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    result = inherit_dependency_checks(
        std_dir,
        {
            "std/a.mm": _report("alias_check"),
            "std/b.mm": {},
        },
    )
    dependent = result["files"]["std/b.mm"]
    assert dependent["inherited"] == {"alias_check": ["std/a.mm"]}
    assert dependent["dependencies_without_report"] == []
    assert "dependency_verification" not in dependent["checks_not_performed"]


def test_self_import_through_alias_does_not_inherit_own_checks(
    tmp_path: Path,
) -> None:
    std_dir = _std(
        tmp_path,
        {"b.mm": 'import "std/alias_b.mm";\n'},
    )
    alias = std_dir / "alias_b.mm"
    try:
        alias.symlink_to(std_dir / "b.mm")
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    result = inherit_dependency_checks(
        std_dir,
        {"std/b.mm": _report("own_check")},
    )
    record = result["files"]["std/b.mm"]
    assert record["own"] == ["own_check"]
    assert record["inherited"] == {}
    assert record["dependencies_without_report"] == []


def test_unknown_reports_are_sorted(tmp_path: Path) -> None:
    std_dir = _std(tmp_path, {"a.mm": ""})
    result = inherit_dependency_checks(
        std_dir,
        {"std/z.mm": {}, "std/a.mm": {}, "other.mm": {}},
    )

    assert result["unknown_reports"] == ["other.mm", "std/z.mm"]


@pytest.mark.parametrize(
    "reports",
    [
        [],
        {1: {}},
        {"std/a.mm": []},
        {"std/a.mm": {"checks_not_performed": "not-a-list"}},
        {
            "std/a.mm": {
                "schema_version": UNPERFORMED_CHECK_RECOVERY_SCHEMA,
                "unrecovered": "not-a-list",
            }
        },
    ],
)
def test_invalid_reports_raise_value_error(tmp_path: Path, reports: object) -> None:
    std_dir = _std(tmp_path, {"a.mm": ""})
    with pytest.raises(ValueError):
        inherit_dependency_checks(std_dir, reports)  # type: ignore[arg-type]


def test_non_string_checks_are_skipped(tmp_path: Path) -> None:
    std_dir = _std(
        tmp_path,
        {
            "a.mm": "",
            "b.mm": 'import "std/a";\n',
            "c.mm": 'import "std/b";\n',
        },
    )
    result = inherit_dependency_checks(
        std_dir,
        {
            "std/a.mm": {"checks_not_performed": ["own", None, 7]},
            "std/b.mm": {
                "schema_version": UNPERFORMED_CHECK_RECOVERY_SCHEMA,
                "unrecovered": ["recovery", None, {}],
            },
            "std/c.mm": {},
        },
    )

    assert result["files"]["std/a.mm"]["own"] == ["own"]
    assert result["files"]["std/b.mm"]["inherited"] == {"own": ["std/a.mm"]}
    assert result["files"]["std/c.mm"]["inherited"] == {
        "own": ["std/a.mm"],
        "recovery": ["std/b.mm"],
    }


def test_output_is_deterministic(tmp_path: Path) -> None:
    std_dir = _std(
        tmp_path,
        {
            "a.mm": "",
            "b.mm": 'import "std/a";\n',
            "c.mm": 'import "std/a";\n',
        },
    )
    first = inherit_dependency_checks(
        std_dir,
        {
            "std/a.mm": _report("z", "a"),
            "std/b.mm": _report("b"),
            "std/c.mm": {},
        },
    )
    second = inherit_dependency_checks(
        std_dir,
        {
            "std/c.mm": {},
            "std/b.mm": _report("b"),
            "std/a.mm": _report("z", "a"),
        },
    )

    assert first == second
    assert first["checks_not_performed"] == [
        "re_verification",
        "evidence_binding",
        "symbol_resolution",
        "external_std_path_resolution",
    ]


def test_file_record_can_be_folded_by_recovery_evaluator(
    tmp_path: Path,
) -> None:
    std_dir = _std(
        tmp_path,
        {"a.mm": "", "b.mm": 'import "std/a";\n'},
    )
    result = inherit_dependency_checks(
        std_dir,
        {"std/a.mm": _report("signature_verification"), "std/b.mm": {}},
    )

    evaluation = evaluate_unperformed_check_recovery(result["files"]["std/b.mm"], [])
    assert evaluation["unrecovered"] == ["signature_verification"]
