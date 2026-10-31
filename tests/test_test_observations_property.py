from __future__ import annotations

from copy import deepcopy

import pytest

from agent.test_observations import (
    _format_property,
    _format_property_call,
    _property_metadata,
    align_harvest_to_spec,
    observation_feedback_parts,
    observation_prompt_context,
    observation_summary,
    observation_warnings,
)


PROPERTY_HARVEST = {
    "schema": "mumei.test-harvest/v1",
    "targets": {"f": {"python": {"params": ["a", "b"]}}},
    "observations": [
        {
            "kind": "property",
            "target": "f",
            "args": {"a": {"var": "x"}, "b": 3},
            "test": "test_f_nonneg",
            "file": "test_f.py",
            "line": 12,
            "variables": [
                {"name": "x", "type": "i64", "min": 0, "max": 100},
                {"name": "y", "type": "i64"},
                {"name": "b", "type": "bool"},
            ],
            "assumptions": ["(x != 5)"],
            "predicate": "(result >= x)",
        }
    ],
}
SPEC = {
    "atoms": [
        {
            "name": "f",
            "inputs": [{"name": "a"}, {"name": "b"}],
        }
    ]
}


@pytest.mark.parametrize(
    ("variables", "expected"),
    [
        ([{"name": "x", "type": "i64", "min": 0, "max": 100}], "x in [0, 100]"),
        ([{"name": "x", "type": "i64"}], "x: i64"),
        ([{"name": "x", "type": "i64", "min": 0}], "x >= 0"),
        ([{"name": "x", "type": "i64", "max": 100}], "x <= 100"),
        ([{"name": "b", "type": "bool", "min": 1}], "b: bool"),
    ],
)
@pytest.mark.parametrize(
    ("assumptions", "assumption_text"),
    [
        ([], ""),
        (["(x != 5)"], ", assuming (x != 5)"),
        (["(x != 5)", "(y > 0)"], ", assuming (x != 5) && (y > 0)"),
    ],
)
def test_property_prompt_quantifies_variables_and_assumptions(
    variables,
    expected: str,
    assumptions,
    assumption_text: str,
) -> None:
    prompt = observation_prompt_context(
        {
            "targets": {"f": {"python": {"params": ["a", "b"]}}},
            "observations": [
                {
                    "kind": "property",
                    "target": "f",
                    "args": {"a": {"var": "x"}, "b": 3},
                    "test": "test_property",
                    "file": "test_f.py",
                    "line": 2,
                    "variables": variables,
                    "assumptions": assumptions,
                    "predicate": "result >= x",
                }
            ],
        }
    )
    assert f"- test_property (test_f.py:2): for all {expected}{assumption_text}:" in prompt
    assert "f(a=x, b=3) satisfies result >= x" in prompt


def test_property_prompt_formats_argument_shapes_and_fallback_order() -> None:
    assert _format_property_call(
        "f", {"b": 3, "a": {"var": "x"}}, ["a", "b"]
    ) == "f(a=x, b=3)"
    assert _format_property_call(
        "f", {"z": 3, "x": {"var": "v"}}, ["a", "b"]
    ) == "f(x=v, z=3)"
    assert _format_property_call(
        "f", [{"var": "x"}, 3], ["a", "b"]
    ) == "f(a=x, b=3)"
    assert _format_property_call("f", [{"var": "x"}, 3], ["a"]) == "f(x, 3)"
    assert _format_property_call("f", None, ["a"]) == "f()"
    assert _format_property(
        "f(a=x)",
        [{"name": 7}, {"name": "x", "type": "i64"}],
        [],
        None,
    ) == "for all x: i64: f(a=x) satisfies <unknown>"


def test_property_prompt_uses_generated_inputs_when_metadata_is_unknown() -> None:
    assert _format_property("f()", None, None, "true") == (
        "for all generated inputs: f() satisfies true"
    )
    assert _format_property("f()", [{"name": "x", "type": "i64"}], None, "true") == (
        "for all generated inputs: f() satisfies true"
    )
    assert _format_property("f()", [], [], "true") == (
        "for all generated inputs: f() satisfies true"
    )


def test_property_header_is_added_only_for_selected_property_observations() -> None:
    property_header = (
        "Ensures must imply every property predicate for all inputs in the stated "
        "ranges that satisfy the assumptions and requires."
    )
    assert property_header in observation_prompt_context(
        {"observations": [PROPERTY_HARVEST["observations"][0]]}
    )
    cutoff_observations = [
        {
            "kind": "example",
            "target": "f",
            "args": [index],
            "result": index,
            "file": "a_test.py",
            "line": index,
        }
        for index in range(40)
    ] + [{"kind": "property", "file": "z_test.py", "line": 1}]
    assert property_header not in observation_prompt_context(
        {"observations": cutoff_observations}
    )
    assert property_header not in observation_prompt_context(
        {"observations": [{"kind": "example"}]}
    )


def test_existing_observation_prompt_is_byte_identical_without_properties() -> None:
    prompt = observation_prompt_context(
        {
            "observations": [
                {
                    "kind": "example",
                    "target": "add",
                    "args": [2, 3],
                    "result": 5,
                    "test": "test_add",
                    "file": "test_math.py",
                    "line": 2,
                },
                {
                    "kind": "relation",
                    "target": "add",
                    "args": {"b": 2, "a": 1},
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
    assert prompt == (
        "# Observed test behavior\n"
        "Atoms for tested functions must use the same function name and parameter order.\n"
        "Ensures must hold for every example and relation; requires must exclude rejected inputs.\n"
        "- add(2, 3) == 5; args: [2,3] (test_add test_math.py:2)\n"
        "- add(x…) with result >= 0; args: {\"a\":1,\"b\":2} "
        "(test_relation test_math.py:3)\n"
        "- add(…) is rejected; args: [-1,2] (test_reject test_math.py:4)"
    )


def test_mixed_prompt_renders_all_four_observation_kinds() -> None:
    observations = [
        {"kind": kind, "target": "f", "args": [1], "test": f"test_{kind}",
         "file": "test_f.py", "line": index + 1}
        for index, kind in enumerate(("example", "relation", "property", "rejects"))
    ]
    observations[0]["result"] = 1
    observations[1]["predicate"] = "result >= 0"
    observations[2].update(
        variables=[{"name": "x", "type": "i64"}],
        assumptions=[],
        predicate="result == x",
    )
    prompt = observation_prompt_context({"observations": observations})
    assert "- f(1) == 1;" in prompt
    assert "- f(x…) with result >= 0;" in prompt
    assert "- test_property (test_f.py:3): for all x: i64:" in prompt
    assert "- f(…) is rejected;" in prompt


def test_property_observation_alignment_keeps_variable_references_and_input_immutable() -> None:
    harvest = deepcopy(PROPERTY_HARVEST)
    harvest["targets"]["f"]["rust"] = {"params": ["b", "a"]}
    harvest["observations"].extend(
        [
            {
                "kind": "property",
                "target": "f",
                "args": [{"var": "x"}, 3],
                "file": "test_f.py",
            },
            {
                "kind": "property",
                "target": "f",
                "args": {"a": {"var": "x"}},
                "file": "test_f.py",
            },
            {
                "kind": "property",
                "target": "f",
                "args": {"a": {"var": "x"}, "b": 3},
                "file": "f_test.rs",
            },
        ]
    )
    original = deepcopy(harvest)
    aligned = align_harvest_to_spec(harvest, {"atoms": []})
    assert aligned["observations"][0]["args"] == [{"var": "x"}, 3]
    assert aligned["observations"][1]["args"] == [{"var": "x"}, 3]
    assert aligned["observations"][2]["args"] == {"a": {"var": "x"}}
    assert aligned["observations"][3]["args"] == [3, {"var": "x"}]
    assert harvest == original


def test_property_metadata_prefers_result_fields_and_looks_up_harvest() -> None:
    result = {
        **PROPERTY_HARVEST["observations"][0],
        "variables": [{"name": "result-var", "type": "i64"}],
        "assumptions": [],
    }
    assert _property_metadata(result, PROPERTY_HARVEST) == (
        result["variables"], []
    )
    missing_fields = {
        key: value for key, value in result.items()
        if key not in {"variables", "assumptions"}
    }
    assert _property_metadata(missing_fields, PROPERTY_HARVEST) == (
        PROPERTY_HARVEST["observations"][0]["variables"],
        PROPERTY_HARVEST["observations"][0]["assumptions"],
    )
    assert _property_metadata(missing_fields, None) == (None, None)


def test_property_metadata_narrows_ambiguous_harvest_matches_by_args() -> None:
    first = deepcopy(PROPERTY_HARVEST["observations"][0])
    second = deepcopy(first)
    second["args"] = {"a": {"var": "y"}, "b": 4}
    second["variables"] = [{"name": "y", "type": "i64"}]
    harvest = {"observations": [first, second]}
    result = {
        key: value for key, value in first.items()
        if key not in {"variables", "assumptions"}
    }
    assert _property_metadata(result, harvest) == (
        first["variables"], first["assumptions"]
    )
    second["args"] = deepcopy(first["args"])
    assert _property_metadata(result, harvest) == (None, None)


def test_property_feedback_blocks_contradictions_and_requires_admits_rejected() -> None:
    row = {
        **PROPERTY_HARVEST["observations"][0],
        "verdict": "contradicts_ensures",
    }
    blocking, soft = observation_feedback_parts(
        {"results": [row]}, SPEC, PROPERTY_HARVEST
    )
    assert blocking == [
        "test test_f_nonneg (test_f.py:12) checks for all x in [0, 100], "
        "y: i64, b: bool, assuming (x != 5): f(a=x, b=3) satisfies "
        "(result >= x), but atom f's ensures contradict the predicate for "
        "every generated input that requires admits"
    ]
    assert soft == []
    row["verdict"] = "requires_admits_rejected"
    assert observation_feedback_parts({"results": [row]}, SPEC, PROPERTY_HARVEST)[0] == [
        "test test_f_nonneg (test_f.py:12) checks for all x in [0, 100], "
        "y: i64, b: bool, assuming (x != 5): f(a=x, b=3) satisfies "
        "(result >= x), but got verdict requires_admits_rejected, which is "
        "not a property verdict"
    ]


@pytest.mark.parametrize("detail", [None, ""])
def test_not_entailed_feedback_is_retryable_without_empty_counterexample(detail) -> None:
    row = {
        **PROPERTY_HARVEST["observations"][0],
        "verdict": "not_entailed",
        "detail": detail,
    }
    blocking, soft = observation_feedback_parts(
        {"results": [row]}, SPEC, PROPERTY_HARVEST
    )
    assert blocking == []
    assert soft == [
        "test test_f_nonneg (test_f.py:12) checks for all x in [0, 100], "
        "y: i64, b: bool, assuming (x != 5): f(a=x, b=3) satisfies "
        "(result >= x), but atom f's ensures do not guarantee it; strengthen "
        "ensures so that (result >= x) holds whenever requires and the test's "
        "assumptions hold"
    ]


def test_not_entailed_feedback_adds_detail_and_precedes_missing_atom() -> None:
    rows = [
        {
            "kind": "example", "target": "missing", "file": "test_f.py",
            "line": 13, "test": "test_missing", "verdict": "not_checked",
            "detail": "no_atom",
        },
        {
            **PROPERTY_HARVEST["observations"][0],
            "verdict": "not_entailed",
            "detail": "x=7, result=1",
        },
    ]
    _, soft = observation_feedback_parts(
        {"results": rows}, SPEC, PROPERTY_HARVEST
    )
    assert soft[0].endswith("(detail: x=7, result=1)")
    assert soft[1] == "No atom in the extracted spec for harvested targets: missing"


@pytest.mark.parametrize(
    "verdict",
    [
        "entailed",
        "domain_exceeds_requires",
        "not_checked",
    ],
)
def test_property_nonblocking_verdicts_do_not_produce_feedback(verdict: str) -> None:
    row = {**PROPERTY_HARVEST["observations"][0], "verdict": verdict}
    assert observation_feedback_parts(
        {"results": [row]}, SPEC, PROPERTY_HARVEST
    ) == ([], [])


@pytest.mark.parametrize(
    ("verdict", "detail", "expected"),
    [
        (
            "not_entailed",
            "result=0",
            "test test_f_nonneg (test_f.py:12) checks for all x in [0, 100], "
            "y: i64, b: bool, assuming (x != 5): f(a=x, b=3) satisfies "
            "(result >= x), but atom f's ensures do not guarantee it "
            "(detail: result=0)",
        ),
        (
            "domain_exceeds_requires",
            None,
            "test test_f_nonneg (test_f.py:12) checks for all x in [0, 100], "
            "y: i64, b: bool, assuming (x != 5): f(a=x, b=3) satisfies "
            "(result >= x), but its generated inputs exceed atom f's requires; "
            "the predicate holds where requires admits the input",
        ),
        (
            "outside_requires",
            None,
            "test test_f_nonneg (test_f.py:12) checks for all x in [0, 100], "
            "y: i64, b: bool, assuming (x != 5): f(a=x, b=3) satisfies "
            "(result >= x), but no generated input satisfies atom f's requires",
        ),
        (
            "inconclusive",
            "solver timeout",
            "test test_f_nonneg (test_f.py:12) checks for all x in [0, 100], "
            "y: i64, b: bool, assuming (x != 5): f(a=x, b=3) satisfies "
            "(result >= x), but mumei observe could not decide it: solver timeout",
        ),
        (
            "not_checked",
            "unsupported observation kind",
            "property test test_f_nonneg (test_f.py:12) was not checked: "
            "unsupported observation kind; this mumei build does not support "
            "property observations",
        ),
        (
            "not_checked",
            "map_args: parameter names differ",
            "property test test_f_nonneg (test_f.py:12) was not checked: "
            "map_args: parameter names differ",
        ),
    ],
)
def test_property_warning_verdicts(
    verdict: str,
    detail: str | None,
    expected: str,
) -> None:
    row = {
        **PROPERTY_HARVEST["observations"][0],
        "verdict": verdict,
        "detail": detail,
    }
    assert observation_warnings(
        {"results": [row]}, SPEC, PROPERTY_HARVEST
    ) == [expected]


def test_property_warning_unrecognized_verdicts_and_non_property_verdicts() -> None:
    results = [
        {"kind": "example", "test": "example", "file": "a.py", "line": 1,
         "verdict": "new_verdict"},
        {**PROPERTY_HARVEST["observations"][0], "verdict": "consistent"},
        {**PROPERTY_HARVEST["observations"][0], "verdict": None},
        {
            key: value
            for key, value in PROPERTY_HARVEST["observations"][0].items()
            if key != "kind"
        },
        {**PROPERTY_HARVEST["observations"][0], "verdict": "entailed"},
    ]
    assert observation_warnings({"results": results}, SPEC, PROPERTY_HARVEST) == [
        "test example (a.py:1) got unrecognized verdict 'new_verdict' from "
        "mumei observe; treating it as unchecked",
        "test test_f_nonneg (test_f.py:12) got unrecognized verdict None from "
        "mumei observe; treating it as unchecked",
        "test test_f_nonneg (test_f.py:12) checks for all x in [0, 100], "
        "y: i64, b: bool, assuming (x != 5): f(a=x, b=3) satisfies "
        "(result >= x), but got verdict consistent, which is not a property "
        "verdict; treating it as unchecked",
        "test test_f_nonneg (test_f.py:12) got unrecognized verdict None from "
        "mumei observe; treating it as unchecked",
    ]
    assert observation_warnings(
        {"results": [{"kind": "example", "verdict": "outside_requires"}]},
        SPEC,
    ) == [
        "test <unknown> (<unknown>:?) observed <unknown>() == null, but atom "
        "<unknown>'s requires excludes these arguments"
    ]


def test_not_checked_no_atom_is_not_a_warning_but_missing_detail_is() -> None:
    base = PROPERTY_HARVEST["observations"][0]
    assert observation_warnings(
        {
            "results": [
                {**base, "verdict": "not_checked", "detail": "no_atom"},
                {**base, "verdict": "not_checked"},
            ]
        },
        SPEC,
        PROPERTY_HARVEST,
    ) == [
        "property test test_f_nonneg (test_f.py:12) was not checked: no detail"
    ]


def test_inconclusive_warning_stringifies_nonempty_detail() -> None:
    row = {
        **PROPERTY_HARVEST["observations"][0],
        "verdict": "inconclusive",
        "detail": 3,
    }
    assert observation_warnings(
        {"results": [row]}, SPEC, PROPERTY_HARVEST
    ) == [
        "test test_f_nonneg (test_f.py:12) checks for all x in [0, 100], "
        "y: i64, b: bool, assuming (x != 5): f(a=x, b=3) satisfies "
        "(result >= x), but mumei observe could not decide it: 3"
    ]


@pytest.mark.parametrize(
    "verdict",
    [
        "entailed",
        "not_entailed",
        "contradicts_ensures",
        "domain_exceeds_requires",
        "outside_requires",
        "inconclusive",
        "not_checked",
        "requires_admits_rejected",
        "consistent",
    ],
)
def test_property_messages_never_double_quantify_or_mislabel_details(
    verdict: str,
) -> None:
    row = {
        **PROPERTY_HARVEST["observations"][0],
        "verdict": verdict,
        "detail": "contract does not entail the property",
    }
    blocking, soft = observation_feedback_parts(
        {"results": [row]}, SPEC, PROPERTY_HARVEST
    )
    warnings = observation_warnings(
        {"results": [row]}, SPEC, PROPERTY_HARVEST
    )

    assert all(
        "for for " not in message and "counterexample:" not in message
        for message in blocking + soft + warnings
    )


def test_all_verdicts_summary_and_unrecognized_suffix() -> None:
    verdicts = [
        "consistent",
        "contradicts_ensures",
        "domain_exceeds_requires",
        "entailed",
        "inconclusive",
        "not_checked",
        "not_entailed",
        "outside_requires",
        "rejection_explained",
        "requires_admits_rejected",
    ]
    report = {"results": [{"verdict": verdict} for verdict in verdicts]}
    assert observation_summary(report) == (
        "Observation checks: consistent=1, contradicts_ensures=1, "
        "domain_exceeds_requires=1, entailed=1, inconclusive=1, not_checked=1, "
        "not_entailed=1, outside_requires=1, rejection_explained=1, "
        "requires_admits_rejected=1"
    )
    assert observation_summary(
        {"results": [{"verdict": "mystery"}, {"verdict": None}]}
    ).endswith("requires_admits_rejected=0, unrecognized=2")
    assert observation_summary({"results": [{"verdict": "mystery"}], "totals": {
        "consistent": 7,
    }}).startswith("Observation checks: consistent=7,")
