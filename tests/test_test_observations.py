from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.test_observations import (
    ObservationCheckError,
    align_harvest_to_spec,
    check_observations,
    observation_feedback,
    observation_prompt_context,
    observation_summary,
    spec_to_observe_module,
)


def test_align_harvest_to_spec_uses_language_specific_parameter_order() -> None:
    harvest = {
        "targets": {
            "f": {
                "python": {"params": ["left", "right"]},
                "rust": {"params": ["rhs", "lhs"]},
            }
        },
        "observations": [
            {
                "target": "f",
                "file": "test_f.py",
                "args": {"right": 2, "left": 1},
            },
            {
                "target": "f",
                "file": "f_test.rs",
                "args": {"lhs": 3, "rhs": 4},
            },
            {"target": "unknown", "file": "test_f.py", "args": {"x": 5}},
            {"target": "f", "file": "test_f.py", "args": {"left": 6}},
        ],
    }

    aligned = align_harvest_to_spec(harvest, {"atoms": []})

    assert aligned["observations"][0]["args"] == [1, 2]
    assert aligned["observations"][1]["args"] == [4, 3]
    assert aligned["observations"][2]["args"] == {"x": 5}
    assert aligned["observations"][3]["args"] == {"left": 6}
    assert harvest["observations"][0]["args"] == {"right": 2, "left": 1}


def test_spec_to_observe_module_keeps_real_signatures_and_trust() -> None:
    module = spec_to_observe_module(
        {
            "atoms": [
                {
                    "name": "add",
                    "inputs": [
                        {"name": "left", "type": "i64"},
                        {"name": "right", "type": "i64"},
                    ],
                    "return_type": "i64",
                    "requires": "left >= 0",
                    "ensures": "result == left + right",
                }
            ]
        }
    )

    assert "trusted atom add(left: i64, right: i64) -> i64" in module
    assert "requires: left >= 0;" in module
    assert "ensures: result == left + right;" in module


@pytest.mark.parametrize(
    ("result", "message"),
    [
        ({"returncode": 4, "report": None, "stderr": "old mumei"}, "exit code 4"),
        ({"returncode": 2, "report": {}, "stderr": ""}, "exit code 2"),
        ({"returncode": 0, "report": None, "stderr": ""}, "no JSON report"),
        ({"returncode": 0, "report": [], "stderr": ""}, "no JSON report"),
        (
            {"returncode": 1, "report": {"schema": "old"}, "stderr": ""},
            "unexpected report schema",
        ),
        (
            {
                "returncode": 0,
                "report": {"schema": "mumei.observation-check/v1"},
                "stderr": "",
            },
            "no results array",
        ),
    ],
)
def test_check_observations_fails_closed(
    result: dict,
    message: str,
    tmp_path: Path,
) -> None:
    class FakeMumei:
        def observe_check(self, module_path: str, harvest_path: str):
            assert Path(module_path).is_file()
            payload = json.loads(Path(harvest_path).read_text(encoding="utf-8"))
            assert payload["schema"] == "mumei.test-harvest/v1"
            assert Path(module_path).parent != Path.cwd()
            return result

    with pytest.raises(ObservationCheckError, match=message):
        check_observations(
            "trusted atom f() -> i64 { body: { 0 } }\n",
            {"schema": "mumei.test-harvest/v1", "observations": []},
            FakeMumei(),
        )


def test_check_observations_accepts_exit_one_and_cleans_temporary_files() -> None:
    captured: dict[str, Path] = {}

    class FakeMumei:
        def observe_check(self, module_path: str, harvest_path: str):
            captured["module"] = Path(module_path)
            captured["harvest"] = Path(harvest_path)
            return {
                "returncode": 1,
                "report": {
                    "schema": "mumei.observation-check/v1",
                    "results": [],
                },
                "stderr": "",
            }

    report = check_observations(
        "trusted atom f() -> i64 { body: { 0 } }\n",
        {"schema": "mumei.test-harvest/v1", "observations": []},
        FakeMumei(),
    )

    assert report["schema"] == "mumei.observation-check/v1"
    assert not captured["module"].exists()
    assert not captured["harvest"].exists()


def test_observation_feedback_covers_blocking_verdicts_in_stable_order() -> None:
    report = {
        "results": [
            {
                "kind": "example",
                "target": "add",
                "test": "test_add",
                "file": "tests/test_lib.py",
                "line": 2,
                "args": [2, 3],
                "result": 5,
                "verdict": "contradicts_ensures",
            },
            {
                "kind": "relation",
                "target": "add",
                "test": "test_relation",
                "file": "tests/test_lib.py",
                "line": 3,
                "args": [1, -2],
                "predicate": "result >= 0",
                "verdict": "contradicts_ensures",
            },
            {
                "kind": "rejects",
                "target": "add",
                "test": "test_rejects",
                "file": "tests/test_lib.py",
                "line": 4,
                "args": [-1, 2],
                "verdict": "requires_admits_rejected",
            },
            {
                "kind": "example",
                "target": "missing",
                "test": "test_missing",
                "file": "tests/test_lib.py",
                "line": 5,
                "args": [0],
                "verdict": "not_checked",
                "detail": "no_atom",
            },
            {
                "kind": "example",
                "target": "generic",
                "test": "test_generic",
                "file": "tests/test_lib.py",
                "line": 6,
                "args": [0],
                "verdict": "not_checked",
                "detail": "generic_atom",
            },
            {
                "kind": "example",
                "target": "add",
                "test": "test_consistent",
                "file": "tests/test_lib.py",
                "line": 7,
                "verdict": "consistent",
            },
            {
                "kind": "example",
                "target": "add",
                "test": "test_outside",
                "file": "tests/test_lib.py",
                "line": 8,
                "verdict": "outside_requires",
            },
            {
                "kind": "rejects",
                "target": "add",
                "test": "test_explained",
                "file": "tests/test_lib.py",
                "line": 9,
                "verdict": "rejection_explained",
            },
            {
                "kind": "example",
                "target": "add",
                "test": "test_unknown",
                "file": "tests/test_lib.py",
                "line": 10,
                "verdict": "inconclusive",
            },
        ]
    }
    spec = {
        "atoms": [
            {
                "name": "add",
                "inputs": [
                    {"name": "left", "type": "i64"},
                    {"name": "right", "type": "i64"},
                ],
            }
        ]
    }

    expected = [
        "test test_add (tests/test_lib.py:2) observed add(2, 3) == 5, "
        "but atom add's ensures forbids it",
        "test test_relation (tests/test_lib.py:3) observed add(1, -2) with "
        "relation result >= 0, but atom add's ensures forbids it",
        "test test_rejects (tests/test_lib.py:4) expects add(-1, 2) to be "
        "rejected, but atom add's requires admits it",
        "No atom in the extracted spec for harvested targets: missing",
    ]
    assert observation_feedback(report, spec) == expected
    assert observation_feedback(report, spec) == expected


def test_observation_summary_counts_every_verdict() -> None:
    report = {
        "results": [
            {"verdict": "consistent"},
            {"verdict": "contradicts_ensures"},
            {"verdict": "inconclusive"},
            {"verdict": "not_checked"},
            {"verdict": "outside_requires"},
            {"verdict": "rejection_explained"},
            {"verdict": "requires_admits_rejected"},
        ]
    }

    assert observation_summary(report) == (
        "Observation checks: consistent=1, contradicts_ensures=1, "
        "inconclusive=1, not_checked=1, outside_requires=1, "
        "rejection_explained=1, requires_admits_rejected=1"
    )


def test_observation_prompt_is_deterministic_and_limited_to_forty() -> None:
    harvest = {
        "observations": [
            {
                "kind": "example",
                "target": "add",
                "args": [index, 1],
                "result": index + 1,
                "test": f"test_{index:02d}",
                "file": "test_lib.py",
                "line": index + 1,
            }
            for index in range(45)
        ]
        + [
            {
                "kind": "relation",
                "target": "add",
                "args": {"a": 1, "b": 2},
                "predicate": "result >= 0",
                "test": "test_relation",
                "file": "test_lib.py",
                "line": 100,
            },
            {
                "kind": "rejects",
                "target": "add",
                "args": [-1, 2],
                "test": "test_reject",
                "file": "test_lib.py",
                "line": 101,
            },
        ]
    }

    prompt = observation_prompt_context(harvest)

    assert prompt.startswith("# Observed test behavior\n")
    assert "same function name and parameter order" in prompt
    assert "Ensures must hold for every example and relation" in prompt
    assert "requires must exclude rejected inputs" in prompt
    assert prompt.count("\n- ") == 40
    assert "test_00" in prompt
    assert "test_39" in prompt
    assert "test_40" not in prompt


def test_observation_prompt_renders_relations_and_rejects() -> None:
    prompt = observation_prompt_context(
        {
            "observations": [
                {
                    "kind": "relation",
                    "target": "add",
                    "args": {"a": 1, "b": 2},
                    "predicate": "result >= 0",
                    "test": "test_relation",
                    "file": "test_math.py",
                    "line": 3,
                },
                {
                    "kind": "rejects",
                    "target": "add",
                    "args": [-1, 2],
                    "test": "test_reject",
                    "file": "test_math.py",
                    "line": 4,
                },
            ]
        }
    )

    assert "add(x…) with result >= 0" in prompt
    assert "args: {\"a\":1,\"b\":2}" in prompt
    assert "add(…) is rejected" in prompt
