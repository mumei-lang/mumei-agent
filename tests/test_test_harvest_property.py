from __future__ import annotations

from pathlib import Path

import pytest

from agent.test_harvest import harvest_tests


def _write(path: Path, source: str) -> Path:
    path.write_text(source, encoding="utf-8")
    return path


def _python_report(tmp_path: Path, source: str) -> dict:
    return harvest_tests([_write(tmp_path / "test_property.py", source)], None, None)


def _rust_report(tmp_path: Path, source: str) -> dict:
    return harvest_tests([_write(tmp_path / "property.rs", source)], None, None)


def test_hypothesis_property_emits_variables_assumptions_and_named_args(
    tmp_path: Path,
) -> None:
    report = _python_report(
        tmp_path,
        "from hypothesis import assume, given\n"
        "from hypothesis import strategies as st\n"
        "def add(left, right): return left + right\n"
        "@given(x=st.integers(0, 100), flag=st.booleans())\n"
        "def test_add(x, flag):\n"
        "    assume(x != 5)\n"
        "    assert add(x, 3) >= x\n",
    )

    assert report["observations"] == [
        {
            "kind": "property",
            "target": "add",
            "args": {"left": {"var": "x"}, "right": 3},
            "test": "test_add",
            "file": "test_property.py",
            "line": 7,
            "variables": [
                {"name": "x", "type": "i64", "min": 0, "max": 100},
                {"name": "flag", "type": "bool"},
            ],
            "assumptions": ["(x != 5)"],
            "predicate": "(result >= x)",
        }
    ]
    assert report["totals"]["observations"]["property"] == 1


@pytest.mark.parametrize(
    ("strategy", "variable"),
    [
        ("st.integers()", {"name": "x", "type": "i64"}),
        ("st.integers(min_value=-8)", {"name": "x", "type": "i64", "min": -8}),
        ("st.integers(max_value=-2)", {"name": "x", "type": "i64", "max": -2}),
        (
            "st.integers(-4, -1)",
            {"name": "x", "type": "i64", "min": -4, "max": -1},
        ),
    ],
)
def test_hypothesis_integer_strategy_bounds(
    tmp_path: Path, strategy: str, variable: dict
) -> None:
    report = _python_report(
        tmp_path,
        "from hypothesis import given\n"
        "from hypothesis import strategies as st\n"
        "def f(value): return value\n"
        f"@given({strategy})\n"
        "def test_f(x):\n"
        "    assert f(x) >= x\n",
    )

    assert report["observations"][0]["variables"] == [variable]
    assert report["observations"][0]["args"] == {"value": {"var": "x"}}


def test_hypothesis_aliases_and_method_self_parameter(tmp_path: Path) -> None:
    report = _python_report(
        tmp_path,
        "import hypothesis as h\n"
        "from hypothesis import given as g\n"
        "from hypothesis import example, settings\n"
        "import hypothesis.strategies as st\n"
        "def f(value): return value\n"
        "class TestF:\n"
        "    @settings(max_examples=3)\n"
        "    @example(1)\n"
        "    @h.given(st.integers(min_value=2))\n"
        "    def test_one(self, x):\n"
        "        assert f(x) > 0\n"
        "    @g(x=st.integers(max_value=9))\n"
        "    def test_two(self, x):\n"
        "        self.assertGreaterEqual(f(x), x)\n",
    )

    assert [item["kind"] for item in report["observations"]] == [
        "property",
        "property",
    ]
    assert report["observations"][0]["variables"] == [
        {"name": "x", "type": "i64", "min": 2}
    ]
    assert report["observations"][1]["variables"] == [
        {"name": "x", "type": "i64", "max": 9}
    ]
    assert "given" not in report["targets"]


def test_hypothesis_boolean_generator_can_be_a_target_argument(
    tmp_path: Path,
) -> None:
    report = _python_report(
        tmp_path,
        "from hypothesis import given\n"
        "from hypothesis import strategies as st\n"
        "def select(value, enabled): return value if enabled else 0\n"
        "@given(st.integers(), enabled=st.booleans())\n"
        "def test_select(x, enabled):\n"
        "    assert select(x, enabled) >= 0\n",
    )

    assert report["observations"][0]["args"] == {
        "value": {"var": "x"},
        "enabled": {"var": "enabled"},
    }
    assert report["observations"][0]["variables"] == [
        {"name": "x", "type": "i64"},
        {"name": "enabled", "type": "bool"},
    ]


@pytest.mark.parametrize(
    "strategy",
    [
        "st.integers().filter(lambda x: x > 0)",
        "st.integers().map(abs)",
        "st.floats()",
        "st.lists(st.integers())",
        "st.just(1)",
        "st.sampled_from([1, 2])",
        "st.data()",
        "st.integers(min_value=LOWER)",
        "st.composite(lambda: st.integers())",
    ],
)
def test_unsupported_hypothesis_strategies_skip_the_whole_test(
    tmp_path: Path, strategy: str
) -> None:
    report = _python_report(
        tmp_path,
        "from hypothesis import given\n"
        "from hypothesis import strategies as st\n"
        "def f(value): return value\n"
        f"@given({strategy})\n"
        "def test_f(x):\n"
        "    assert f(x) > 0\n",
    )

    assert report["observations"] == []
    assert [item["reason"] for item in report["skipped"]] == [
        "unsupported_strategy"
    ]


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ("assume(x != 0)\nassert f(x) > 0", None),
        ("assert f(x) > 0\nassume(x != 0)", "unsupported_assumption"),
        ("if x > 0:\n    assume(x != 0)\nassert f(x) > 0", "unsupported_assumption"),
        ("with pytest.raises(ValueError):\n    f(x)", "unsupported_expression"),
        ("assert f(x + 1) > 0", "non_literal_argument"),
        ("assert f(x) > limit", "non_literal_argument"),
        ("assert f(x) > 0 and f(2) > 0", "multiple_target_calls"),
    ],
)
def test_hypothesis_assumptions_and_unsupported_expressions(
    tmp_path: Path, body: str, reason: str | None
) -> None:
    report = _python_report(
        tmp_path,
        "from hypothesis import assume, given\n"
        "from hypothesis import strategies as st\n"
        "import pytest\n"
        "def f(value): return value\n"
        "@given(st.integers())\n"
        "def test_f(x):\n"
        + "".join(f"    {line}\n" for line in body.splitlines()),
    )

    if reason is None:
        assert report["observations"][0]["assumptions"] == ["(x != 0)"]
    else:
        assert report["observations"] == []
        assert report["skipped"][0]["reason"] == reason


def test_hypothesis_result_variable_and_conditional_assertion_are_skipped(
    tmp_path: Path,
) -> None:
    result_case = _python_report(
        tmp_path,
        "from hypothesis import given\n"
        "from hypothesis import strategies as st\n"
        "def f(value): return value\n"
        "@given(result=st.integers())\n"
        "def test_f(result):\n"
        "    assert f(result) >= 0\n",
    )
    conditional_case = _python_report(
        tmp_path,
        "from hypothesis import given\n"
        "from hypothesis import strategies as st\n"
        "def f(value): return value\n"
        "@given(st.integers())\n"
        "def test_f(x):\n"
        "    if x > 0:\n"
        "        assert f(x) > 0\n",
    )

    assert result_case["skipped"][0]["reason"] == "unsupported_expression"
    assert conditional_case["skipped"][0]["reason"] == "conditional_assertion"
    assert conditional_case["observations"] == []


def test_property_tests_without_generator_args_stay_properties_and_skip_marks_apply(
    tmp_path: Path,
) -> None:
    report = _python_report(
        tmp_path,
        "import pytest\n"
        "from hypothesis import given\n"
        "from hypothesis import strategies as st\n"
        "def f(value): return value\n"
        "@given()\n"
        "def test_constant():\n"
        "    assert f(1) == 1\n"
        "@given(st.integers())\n"
        "def test_constant_with_unused_generator(x):\n"
        "    assert f(1) == 1\n"
        "@pytest.mark.skip\n"
        "@given(st.integers())\n"
        "def test_skipped(x):\n"
        "    assert f(x) > 0\n"
        "@given(st.integers())\n"
        "@pytest.mark.xfail\n"
        "def test_xfailed(x):\n"
        "    assert f(x) > 0\n",
    )

    assert [item["kind"] for item in report["observations"]] == [
        "property",
        "property",
    ]
    assert report["observations"][0]["args"] == {"value": 1}
    assert report["observations"][1]["args"] == {"value": 1}
    assert report["observations"][1]["variables"] == [
        {"name": "x", "type": "i64"}
    ]
    assert [
        item["reason"] for item in report["skipped"]
    ] == ["test_not_run", "test_not_run"]


def test_rust_proptest_ranges_any_assumptions_and_messages(tmp_path: Path) -> None:
    report = _rust_report(
        tmp_path,
        "fn add(left: i64, right: i64) -> i64 { left + right }\n"
        "fn enabled(value: bool) -> bool { value }\n"
        "mod tests {\n"
        "    use super::*;\n"
        "    proptest! {\n"
        "        #![proptest_config(ProptestConfig::with_cases(8))]\n"
        "        #[test]\n"
        "        fn prop_add(x in -2i64..10i64, flag in any::<bool>()) {\n"
        "            prop_assume!(x != 5);\n"
        '            prop_assert_eq!(add(x, 3), 4, \"sample\");\n'
        "            prop_assert!(add(x, 3) >= x);\n"
        '            assert_ne!(add(x, 2), 0, "plain assertion");\n'
        '            prop_assert_ne!(add(x, 1), 0, "proptest assertion");\n'
        '            assert_eq!(add(x, 1), x + 1, "plain equality");\n'
        '            assert!(enabled(flag), "plain assert");\n'
        "        }\n"
        "    }\n"
        "}\n",
    )

    assert [item["kind"] for item in report["observations"]] == [
        "property",
        "property",
        "property",
        "property",
        "property",
        "property",
    ]
    assert report["observations"][0]["variables"] == [
        {"name": "x", "type": "i64", "min": -2, "max": 9},
        {"name": "flag", "type": "bool"},
    ]
    assert report["observations"][0]["args"] == {
        "left": {"var": "x"},
        "right": 3,
    }
    assert report["observations"][0]["assumptions"] == ["(x != 5)"]
    assert report["observations"][0]["predicate"] == "(result == 4)"
    assert report["observations"][0]["line"] == 10
    assert report["observations"][2]["predicate"] == "(result != 0)"
    assert report["observations"][3]["predicate"] == "(result != 0)"
    assert report["observations"][4]["predicate"] == "(result == (x + 1))"
    assert report["observations"][5]["args"] == {"value": {"var": "flag"}}
    assert report["observations"][5]["variables"][1] == {
        "name": "flag",
        "type": "bool",
    }


@pytest.mark.parametrize(
    ("strategy", "expected"),
    [
        ("0..4", {"min": 0, "max": 3}),
        ("0..=4", {"min": 0, "max": 4}),
        ("any::<i64>()", {}),
        ("any::<bool>()", {}),
        ("-4i64..=-1i64", {"min": -4, "max": -1}),
    ],
)
def test_rust_proptest_supported_strategy_forms(
    tmp_path: Path, strategy: str, expected: dict
) -> None:
    type_name = "bool" if "bool" in strategy else "i64"
    report = _rust_report(
        tmp_path,
        "fn f(value: i64) -> i64 { value }\n"
        "proptest! {\n"
        "    #[test]\n"
        f"    fn prop(x in {strategy}) {{ prop_assert!(f(1) >= 0); }}\n"
        "}\n",
    )

    assert report["observations"][0]["variables"] == [
        {"name": "x", "type": type_name, **expected}
    ]


@pytest.mark.parametrize(
    "strategy",
    ["0..0", "2..1", "2..=1", "0..10u64", "1..=MAX", "any::<u32>()"],
)
def test_unsupported_or_empty_proptest_strategies_skip(
    tmp_path: Path, strategy: str
) -> None:
    report = _rust_report(
        tmp_path,
        "fn f(value: i64) -> i64 { value }\n"
        "proptest! {\n"
        "    #[test]\n"
        f"    fn prop(x in {strategy}) {{ prop_assert!(f(1) >= 0); }}\n"
        "}\n",
    )

    assert report["observations"] == []
    assert report["skipped"][0]["reason"] == "unsupported_strategy"


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ("prop_assert!(f(x) > 0); prop_assume!(x != 0);", "unsupported_assumption"),
        ("if x > 0 { prop_assume!(x != 0); } prop_assert!(f(x) > 0);", "unsupported_assumption"),
        ("prop_assert!(f(x + 1) > 0);", "non_literal_argument"),
        ("prop_assert!(f(x) > bound);", "non_literal_argument"),
        ("prop_assert!(f(x) > 0 && f(1) > 0);", "multiple_target_calls"),
        ("if x > 0 { prop_assert!(f(x) > 0); }", "conditional_assertion"),
    ],
)
def test_rust_proptest_assumptions_and_unsupported_assertions(
    tmp_path: Path, body: str, reason: str
) -> None:
    report = _rust_report(
        tmp_path,
        "fn f(value: i64) -> i64 { value }\n"
        "proptest! {\n"
        "    #[test]\n"
        "    fn prop(x in 0..10) { "
        + body
        + " }\n"
        "}\n",
    )

    assert report["observations"] == []
    assert report["skipped"][0]["reason"] == reason


def test_rust_proptest_should_panic_ignore_and_ordinary_tests(tmp_path: Path) -> None:
    report = _rust_report(
        tmp_path,
        "fn f(value: i64) -> i64 { value }\n"
        "proptest! {\n"
        "    #[test]\n"
        "    #[should_panic]\n"
        "    fn prop_panic(x in 0..10) { prop_assert!(f(x) > 0); }\n"
        "    #[ignore]\n"
        "    #[test]\n"
        "    fn prop_ignore(x in 0..10) { prop_assert!(f(x) > 0); }\n"
        "}\n"
        "#[test]\n"
        "fn ordinary() { assert_eq!(f(1), 1); }\n",
    )

    assert [item["kind"] for item in report["observations"]] == ["example"]
    assert [item["reason"] for item in report["skipped"]] == [
        "unsupported_expression",
        "test_not_run",
    ]


def test_rust_proptest_result_generator_is_unsupported(tmp_path: Path) -> None:
    report = _rust_report(
        tmp_path,
        "fn f(value: i64) -> i64 { value }\n"
        "proptest! {\n"
        "    #[test]\n"
        "    fn prop(result in any::<i64>()) { prop_assert!(f(result) >= 0); }\n"
        "}\n",
    )

    assert report["observations"] == []
    assert report["skipped"][0]["reason"] == "unsupported_expression"


def test_harvest_property_output_is_deterministic(tmp_path: Path) -> None:
    source = _write(
        tmp_path / "test_property.py",
        "from hypothesis import given\n"
        "from hypothesis import strategies as st\n"
        "def f(value): return value\n"
        "@given(st.integers())\n"
        "def test_f(x): assert f(x) >= x\n"
        "def test_ordinary(): assert f(1) == 1\n",
    )

    first = harvest_tests([source], None, None)
    second = harvest_tests([source], None, None)

    assert first == second
    assert [item["kind"] for item in first["observations"]] == [
        "property",
        "example",
    ]


def test_property_targets_stay_language_scoped_and_literals_fit_i64(
    tmp_path: Path,
) -> None:
    python_file = _write(
        tmp_path / "test_property.py",
        "from hypothesis import given\n"
        "from hypothesis import strategies as st\n"
        "def f(value): return value\n"
        "@given(st.integers())\n"
        "def test_python(x): assert f(x) >= x\n"
        "def test_out_of_range(): assert f(9223372036854775808) > 0\n",
    )
    rust_file = _write(
        tmp_path / "property.rs",
        "fn f(value: i64) -> i64 { value }\n"
        "proptest! {\n"
        "    #[test]\n"
        "    fn prop_rust(x in 0..10) {\n"
        "        prop_assert!(f(x) >= x);\n"
        "        prop_assert!(f(9223372036854775808) > 0);\n"
        "    }\n"
        "}\n",
    )

    report = harvest_tests([python_file, rust_file], None, None)

    assert set(report["targets"]["f"]) == {"python", "rust"}
    assert [item["kind"] for item in report["observations"]] == [
        "property",
        "property",
    ]
    assert [
        item["reason"] for item in report["skipped"]
    ] == ["unsupported_expression", "unsupported_expression"]


@pytest.mark.parametrize(
    "body",
    [
        "x = x + 100\nassert f(x) >= 100",
        "x += 100\nassert f(x) >= 100",
        "x: int = x + 100\nassert f(x) >= 100",
        "for x in range(3):\n    pass\nassert f(x) >= 0",
        "with contextlib.nullcontext(1) as x:\n    pass\nassert f(x) >= 0",
        "assert f((x := 5)) == 5",
        "del x\nassert f(x) >= 0",
        "try:\n    pass\nexcept ValueError as x:\n    pass\nassert f(x) >= 0",
        "match 1:\n    case x:\n        pass\nassert f(x) >= 0",
        "match [1, 2]:\n    case [*x]:\n        pass\nassert f(x) >= 0",
        "match {1: 2}:\n    case {**x}:\n        pass\nassert f(x) >= 0",
    ],
)
def test_hypothesis_generator_variable_rebindings_skip_the_test(
    tmp_path: Path, body: str
) -> None:
    report = _python_report(
        tmp_path,
        "import contextlib\n"
        "from hypothesis import given\n"
        "from hypothesis import strategies as st\n"
        "def f(value): return value\n"
        "@given(st.integers(0, 10))\n"
        "def test_f(x):\n"
        + "".join(f"    {line}\n" for line in body.splitlines()),
    )

    assert report["observations"] == []
    assert [item["reason"] for item in report["skipped"]] == [
        "generator_variable_rebound"
    ]


@pytest.mark.parametrize(
    "body",
    [
        "other = x + 100\nassert f(x) >= 0",
        "def helper():\n    x = 100\nhelper()\nassert f(x) >= 0",
    ],
)
def test_hypothesis_other_and_nested_local_writes_do_not_rebind_generator(
    tmp_path: Path, body: str
) -> None:
    report = _python_report(
        tmp_path,
        "from hypothesis import given\n"
        "from hypothesis import strategies as st\n"
        "def f(value): return value\n"
        "@given(st.integers(0, 10))\n"
        "def test_f(x):\n"
        + "".join(f"    {line}\n" for line in body.splitlines()),
    )

    assert len(report["observations"]) == 1
    assert report["skipped"] == []


def test_hypothesis_nested_nonlocal_write_rebinds_generator(tmp_path: Path) -> None:
    report = _python_report(
        tmp_path,
        "from hypothesis import given\n"
        "from hypothesis import strategies as st\n"
        "def f(value): return value\n"
        "@given(st.integers(0, 10))\n"
        "def test_f(x):\n"
        "    def helper():\n"
        "        nonlocal x\n"
        "        x = 100\n"
        "    helper()\n"
        "    assert f(x) >= 0\n",
    )

    assert report["observations"] == []
    assert report["skipped"][0]["reason"] == "generator_variable_rebound"


@pytest.mark.parametrize(
    "body",
    [
        "let x = x + 100;",
        "x += 100;",
        "{ let x = x + 100; }",
        "for x in 0..3 {}",
        "if let x = 1 {}",
        "if let Some(x) = Some(1) {}",
        "match 0 { x => {} }",
        "match Some(0) { Some(x) => {}, _ => {} }",
        "let _ = &mut x;",
        "let mut change = || { x += 100; };",
    ],
)
def test_rust_proptest_generator_variable_rebindings_skip_the_test(
    tmp_path: Path, body: str
) -> None:
    report = _rust_report(
        tmp_path,
        "fn f(value: i64) -> i64 { value }\n"
        "proptest! {\n"
        "    #[test]\n"
        "    fn prop(x in 0..10) {\n"
        f"        {body}\n"
        "        prop_assert!(f(x) >= 0);\n"
        "    }\n"
        "}\n",
    )

    assert report["observations"] == []
    assert report["skipped"][0]["reason"] == "generator_variable_rebound"


def test_rust_mut_generator_parameter_is_a_rebound(tmp_path: Path) -> None:
    report = _rust_report(
        tmp_path,
        "fn f(value: i64) -> i64 { value }\n"
        "proptest! {\n"
        "    #[test]\n"
        "    fn prop(mut x in 0..10) { prop_assert!(f(x) >= 0); }\n"
        "}\n",
    )

    assert report["observations"] == []
    assert report["skipped"][0]["reason"] == "generator_variable_rebound"


def test_rust_write_to_another_local_does_not_rebind_generator(
    tmp_path: Path,
) -> None:
    report = _rust_report(
        tmp_path,
        "fn f(value: i64) -> i64 { value }\n"
        "proptest! {\n"
        "    #[test]\n"
        "    fn prop(x in 0..10) {\n"
        "        let other = x + 100;\n"
        "        prop_assert!(f(x) >= 0);\n"
        "    }\n"
        "}\n",
    )

    assert len(report["observations"]) == 1
    assert report["skipped"] == []
