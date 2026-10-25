from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from agent.__main__ import main as agent_cli_main
from agent import test_harvest
from agent.test_harvest import harvest_tests


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _python_file(
    tmp_path: Path,
    assertion: str,
    *,
    prelude: str = "",
    definition: str = "def add(left, right):\n    return left + right\n",
) -> Path:
    return _write(
        tmp_path / "test_math.py",
        "import unittest\n\n"
        + definition
        + "\n"
        + prelude
        + "class TestMath(unittest.TestCase):\n"
        + "    def test_observation(self):\n"
        + "".join(f"        {line}\n" for line in assertion.splitlines()),
    )


def _rust_file(
    tmp_path: Path,
    assertion: str,
    *,
    prelude: str = "",
    definition: str = "fn add(left: i64, right: i64) -> i64 { left + right }\n",
    extra_tests: str = "",
) -> Path:
    return _write(
        tmp_path / "math.rs",
        definition
        + "\n#[cfg(test)]\nmod tests {\n"
        + "    use super::*;\n"
        + "    "
        + prelude
        + "    #[test]\n"
        + "    fn test_observation() {\n"
        + "".join(f"        {line}\n" for line in assertion.splitlines())
        + "    }\n"
        + extra_tests
        + "}\n",
    )


def _report(path: Path, language: str | None = None, targets: set[str] | None = None) -> dict:
    return harvest_tests([path], language, targets)


@pytest.mark.parametrize(
    ("assertion", "kind"),
    [
        ("assert add(2, 3) == 5", "example"),
        ("assert 5 == add(2, 3)", "example"),
        ("self.assertEqual(add(2, 3), 5)", "example"),
        ("self.assertEqual(5, add(2, 3))", "example"),
        ("self.assertNotEqual(add(2, 3), 5)", "relation"),
        ("self.assertLess(add(2, 3), 5)", "relation"),
        ("self.assertLessEqual(add(2, 3), 5)", "relation"),
        ("self.assertGreater(add(2, 3), 5)", "relation"),
        ("self.assertGreaterEqual(add(2, 3), 5)", "relation"),
        ("self.assertTrue(add(2, 3) > 0)", "relation"),
        ("self.assertFalse(add(2, 3) == 5)", "relation"),
        ("assert add(2, 3)", "relation"),
    ],
)
def test_python_observation_matrix(
    tmp_path: Path, assertion: str, kind: str
) -> None:
    source = _python_file(tmp_path, assertion)

    report = _report(source)

    assert report["totals"]["tests"] == 1
    assert len(report["observations"]) == 1
    observation = report["observations"][0]
    assert observation["kind"] == kind
    assert observation["target"] == "add"
    assert observation["args"] == {"left": 2, "right": 3}


@pytest.mark.parametrize(
    ("assertion", "kind"),
    [
        ("assert_eq!(add(2, 3), 5);", "example"),
        ("assert_eq!(5, super::add(2, 3));", "example"),
        ("assert_ne!(add(2, 3), 5);", "relation"),
        ("assert!(add(2, 3) > 0);", "relation"),
    ],
)
def test_rust_observation_matrix(
    tmp_path: Path, assertion: str, kind: str
) -> None:
    source = _rust_file(tmp_path, assertion)

    report = _report(source)

    assert report["totals"]["tests"] == 1
    assert len(report["observations"]) == 1
    observation = report["observations"][0]
    assert observation["kind"] == kind
    assert observation["target"] == "add"
    assert observation["args"] == {"left": 2, "right": 3}


def test_python_relations_expand_chained_comparisons_and_substitute_bindings(
    tmp_path: Path,
) -> None:
    source = _python_file(
        tmp_path,
        "lower = -2\n"
        "assert lower <= module.add(3, 4) < 10",
        prelude="import module\n",
    )

    report = _report(source)
    observation = report["observations"][0]

    assert observation["kind"] == "relation"
    assert observation["args"] == {"left": 3, "right": 4}
    assert observation["predicate"] == "((-2 <= result) && (result < 10))"


def test_python_assert_false_and_arithmetic_predicate_are_translated(
    tmp_path: Path,
) -> None:
    source = _python_file(
        tmp_path,
        "self.assertFalse(add(2, 3) == 5)",
    )

    observation = _report(source)["observations"][0]

    assert observation["predicate"] == "(!(result == 5))"


@pytest.mark.parametrize("operator", ["/", "//", "%"])
def test_python_division_and_modulo_relations_are_skipped(
    tmp_path: Path, operator: str
) -> None:
    source = _python_file(
        tmp_path,
        f"assert add(2, 3) {operator} 2 > 0",
    )

    report = _report(source)

    assert report["observations"] == []
    assert report["skipped"][0]["reason"] == "unsupported_expression"


def test_python_unary_plus_renders_the_operand_without_an_operator(
    tmp_path: Path,
) -> None:
    source = _python_file(tmp_path, "assert +add(2, 3) > 0")

    observation = _report(source)["observations"][0]

    assert observation["predicate"] == "(result > 0)"


def test_python_boolean_and_arithmetic_operators_are_translated(
    tmp_path: Path,
) -> None:
    source = _python_file(
        tmp_path,
        "assert (add(2, 3) % 2 == 1) or (add(3, 4) / 2 > 0)",
    )

    report = _report(source)

    assert report["skipped"][0]["reason"] == "multiple_target_calls"

    source = _python_file(
        tmp_path,
        "assert (add(2, 3) * 2 == 10) or False",
    )
    observation = _report(source)["observations"][0]
    assert observation["predicate"] == "(((result * 2) == 10) || false)"

    source = _python_file(
        tmp_path,
        "assert ((add(2, 3) * 2 - 1) > 1) and True",
    )
    observation = _report(source)["observations"][0]
    assert all(operator in observation["predicate"] for operator in ("*", "-", "&&"))


def test_python_negative_arguments_and_boolean_results_are_literals(
    tmp_path: Path,
) -> None:
    source = _python_file(tmp_path, "assert add(-2, 3) == True")

    observation = _report(source)["observations"][0]

    assert observation["args"] == {"left": -2, "right": 3}
    assert observation["result"] is True


def test_python_rebinding_makes_a_local_non_literal(tmp_path: Path) -> None:
    source = _python_file(
        tmp_path,
        "value = 3\n"
        "value = 4\n"
        "assert add(value, -1) == 5",
    )

    report = _report(source)

    assert report["observations"] == []
    assert report["skipped"][0]["reason"] == "non_literal_argument"


@pytest.mark.parametrize(
    ("assertion", "reason"),
    [
        ("assert 1 == 1", "no_target_call"),
        ("assert add(1, 2) == add(3, 4)", "multiple_target_calls"),
        ("assert add(value, 2) == 5", "non_literal_argument"),
        ("assert add(1, 2) == 5 if flag else False", "unsupported_expression"),
    ],
)
def test_python_skipped_assertion_reasons(
    tmp_path: Path, assertion: str, reason: str
) -> None:
    source = _python_file(tmp_path, assertion)

    report = _report(source)

    assert report["observations"] == []
    assert report["skipped"][0]["reason"] == reason
    assert report["skipped"][0]["text"]


def test_python_raises_context_and_callable_forms_are_rejects(tmp_path: Path) -> None:
    source = _write(
        tmp_path / "test_rejects.py",
        "def explode(value):\n    return value\n\n"
        "def test_context():\n"
        "    with pytest.raises(ValueError):\n"
        "        explode(-1)\n\n"
        "class TestRejects(unittest.TestCase):\n"
        "    def test_callable(self):\n"
        "        self.assertRaises(ValueError, explode, 2)\n",
    )

    report = _report(source)

    assert [item["kind"] for item in report["observations"]] == [
        "rejects",
        "rejects",
    ]
    assert [item["args"] for item in report["observations"]] == [
        {"value": -1},
        {"value": 2},
    ]
    assert all(item["expected"] == "failure" for item in report["observations"])


def test_pytest_raises_callable_form_is_a_reject(tmp_path: Path) -> None:
    source = _write(
        tmp_path / "test_rejects.py",
        "def explode(value):\n    return value\n\n"
        "def test_callable():\n"
        "    pytest.raises(ValueError, explode, 3)\n",
    )

    observation = _report(source)["observations"][0]

    assert observation["kind"] == "rejects"
    assert observation["args"] == {"value": 3}


def test_unittest_testcase_base_is_discovered_without_test_prefix(
    tmp_path: Path,
) -> None:
    source = _write(
        tmp_path / "test_case.py",
        "import unittest\n"
        "def add(x):\n    return x\n"
        "class ArithmeticTests(unittest.TestCase):\n"
        "    def test_add(self):\n"
        "        self.assertEqual(add(4), 4)\n",
    )

    report = _report(source)

    assert report["totals"]["tests"] == 1
    assert report["observations"][0]["kind"] == "example"


def test_python_raises_block_with_multiple_calls_is_ambiguous(tmp_path: Path) -> None:
    source = _write(
        tmp_path / "test_rejects.py",
        "def explode(value):\n    return value\n\n"
        "def test_context():\n"
        "    with pytest.raises(ValueError):\n"
        "        explode(1)\n"
        "        explode(2)\n",
    )

    report = _report(source)

    assert report["observations"] == []
    assert report["skipped"][0]["reason"] == "ambiguous_rejects"


def test_python_raises_block_must_be_a_direct_target_call(tmp_path: Path) -> None:
    source = _write(
        tmp_path / "test_rejects.py",
        "def explode(value):\n    return value\n"
        "def wrapper(value):\n    return value\n\n"
        "def test_context():\n"
        "    with pytest.raises(ValueError):\n"
        "        wrapper(explode(1))\n",
    )

    report = _report(source)

    assert report["observations"] == []
    assert report["skipped"][0]["reason"] == "ambiguous_rejects"


def test_python_classmethod_receiver_is_not_an_explicit_argument(
    tmp_path: Path,
) -> None:
    source = _write(
        tmp_path / "test_classmethod.py",
        "class Math:\n"
        "    @classmethod\n"
        "    def increment(cls, value):\n"
        "        return value + 1\n"
        "def test_increment():\n"
        "    assert Math.increment(2) == 3\n",
    )

    report = _report(source)
    assert report["observations"] == []
    assert report["skipped"][0]["reason"] == "no_target_call"


def test_rust_should_panic_collects_literal_bindings_and_nested_test_module(
    tmp_path: Path,
) -> None:
    source = _write(
        tmp_path / "src" / "math.rs",
        "fn explode(value: i64) -> i64 { value }\n"
        "#[cfg(test)]\n"
        "mod tests {\n"
        "    #[test]\n"
        "    #[should_panic]\n"
        "    fn test_rejects() {\n"
        "        let value: i64 = -3i64;\n"
        "        super::explode(value);\n"
        "    }\n"
        "}\n",
    )

    report = _report(source)

    assert report["observations"][0]["kind"] == "rejects"
    assert report["observations"][0]["target"] == "explode"
    assert report["observations"][0]["args"] == {"value": -3}
    assert report["observations"][0]["expected"] == "failure"


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ("panic!(\"expected\");", "ambiguous_rejects"),
        ("add(1, 2); add(3, 4);", "ambiguous_rejects"),
        ("add(value, 2);", "non_literal_argument"),
    ],
)
def test_rust_should_panic_requires_one_literal_target_call(
    tmp_path: Path, body: str, reason: str
) -> None:
    source = _write(
        tmp_path / "test_math.rs",
        "fn add(left: i64, right: i64) -> i64 { left + right }\n"
        "#[test]\n"
        "#[should_panic]\n"
        "fn test_rejects() {\n"
        + "".join(f"    {line}\n" for line in body.splitlines())
        + "}\n",
    )

    report = _report(source)

    assert report["observations"] == []
    assert report["skipped"][0]["reason"] == reason


def test_rust_rebinding_and_non_literal_expected_value_are_skipped(
    tmp_path: Path,
) -> None:
    source = _write(
        tmp_path / "test_math.rs",
        "fn add(left: i64, right: i64) -> i64 { left + right }\n"
        "#[test]\n"
        "fn test_rebound() {\n"
        "    let left = 1;\n"
        "    let mut right = 2;\n"
        "    right = 3;\n"
        "    assert_eq!(add(left, right), 4);\n"
        "}\n"
        "#[test]\n"
        "fn test_nonliteral_result() {\n"
        "    let left = 1;\n"
        "    assert_eq!(add(left, 2), expected);\n"
        "}\n"
        "#[test]\n"
        "fn test_compound_rebound() {\n"
        "    let mut left = 1;\n"
        "    left += 1;\n"
        "    assert_eq!(add(left, 2), 4);\n"
        "}\n",
    )

    report = _report(source)

    assert report["observations"] == []
    assert [item["reason"] for item in report["skipped"]] == [
        "non_literal_argument",
        "non_literal_argument",
        "non_literal_argument",
    ]


def test_rust_relation_uses_boolean_operators_and_explicit_precedence(
    tmp_path: Path,
) -> None:
    source = _rust_file(
        tmp_path,
        "assert!(add(2, 3) + 1 >= 5 && true);",
    )

    observation = _report(source)["observations"][0]

    assert observation["kind"] == "relation"
    assert observation["predicate"] == "(((result + 1) >= 5) && true)"


@pytest.mark.parametrize("operator", ["/", "%"])
def test_rust_division_and_modulo_relations_are_skipped(
    tmp_path: Path, operator: str
) -> None:
    source = _rust_file(
        tmp_path,
        f"assert!(add(2, 3) {operator} 2 > 0);",
    )

    report = _report(source)

    assert report["observations"] == []
    assert report["skipped"][0]["reason"] == "unsupported_expression"


def test_rust_negative_literal_arguments_and_boolean_values_are_supported(
    tmp_path: Path,
) -> None:
    source = _rust_file(
        tmp_path,
        "assert_eq!(add(-2i64, 3), false);",
    )

    observation = _report(source)["observations"][0]

    assert observation["args"] == {"left": -2, "right": 3}
    assert observation["result"] is False


def test_malformed_file_is_skipped_without_blocking_other_sources(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "sources"
    _write(source_root / "broken.py", "def broken(:\n")
    _write(
        source_root / "valid.py",
        "def add(x):\n    return x\n"
        "def test_add():\n    assert add(2) == 2\n",
    )

    report = harvest_tests([source_root], None, None)

    assert report["totals"]["tests"] == 1
    assert report["observations"][0]["target"] == "add"
    assert any(item["reason"] == "parse_error" for item in report["skipped"])
    assert report["sources"] == ["broken.py", "valid.py"]


def test_rust_parse_error_does_not_block_python_harvest(tmp_path: Path) -> None:
    source_root = tmp_path / "sources"
    _write(source_root / "broken.rs", "fn broken( {")
    _write(
        source_root / "valid.py",
        "def add(x):\n    return x\n"
        "def test_add():\n    assert add(2) == 2\n",
    )

    report = harvest_tests([source_root], None, None)

    assert report["observations"][0]["target"] == "add"
    assert any(item["reason"] == "parse_error" for item in report["skipped"])


def test_target_filter_and_missing_definition_metadata(tmp_path: Path) -> None:
    source = _write(
        tmp_path / "test_targets.py",
        "def add(value):\n    return value\n"
        "def unused(value):\n    return value\n"
        "def test_targets():\n"
        "    assert add(1) == 1\n"
        "    assert missing(2) == 2\n",
    )

    filtered = _report(source, targets={"add"})
    missing = _report(source, targets={"missing"})

    assert list(filtered["targets"]) == ["add"]
    assert [item["target"] for item in filtered["observations"]] == ["add"]
    assert filtered["skipped"][0]["reason"] == "no_target_call"
    assert missing["targets"]["missing"] == {
        "python": {"params": None, "file": None, "line": None}
    }
    assert missing["observations"][0]["args"] == [2]


def test_python_module_attribute_calls_resolve_by_last_component(
    tmp_path: Path,
) -> None:
    source = _write(
        tmp_path / "test_module.py",
        "import module\n"
        "def add(left, right):\n    return left + right\n"
        "def test_module():\n"
        "    assert module.add(2, 3) == 5\n",
    )

    observation = _report(source)["observations"][0]

    assert observation["target"] == "add"
    assert observation["args"] == {"left": 2, "right": 3}


def test_mixed_language_directory_is_relative_and_byte_deterministic(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "project"
    _write(
        source_root / "python" / "test_math.py",
        "def add(x):\n    return x\n"
        "def test_add():\n    assert add(2) == 2\n",
    )
    _write(
        source_root / "rust" / "math.rs",
        "fn add(x: i64) -> i64 { x }\n"
        "#[test]\n"
        "fn test_add() { assert_eq!(add(3i64), 3); }\n",
    )

    first = json.dumps(harvest_tests([source_root], None, None), indent=2, sort_keys=True)
    second = json.dumps(harvest_tests([source_root], None, None), indent=2, sort_keys=True)

    assert first == second
    report = json.loads(first)
    assert report["sources"] == ["python/test_math.py", "rust/math.rs"]
    assert {item["file"] for item in report["observations"]} == set(report["sources"])


def _invoke_cli(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *argv: str,
) -> tuple[int, str, str]:
    monkeypatch.setattr(sys, "argv", ["agent", "harvest-tests", *argv])
    try:
        agent_cli_main()
    except SystemExit as exc:
        code = int(exc.code)
    else:
        code = 0
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_cli_success_zero_observations_and_output_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _write(tmp_path / "empty.py", "def test_empty():\n    pass\n")
    code, stdout, stderr = _invoke_cli(monkeypatch, capsys, str(source))

    assert code == 0
    assert stderr == ""
    assert json.loads(stdout)["totals"]["observations"] == {
        "example": 0,
        "relation": 0,
        "rejects": 0,
    }

    output = tmp_path / "nested" / "observations.json"
    code, stdout, stderr = _invoke_cli(
        monkeypatch,
        capsys,
        str(source),
        "--output",
        str(output),
    )
    assert code == 0
    assert stdout == ""
    assert stderr == ""
    assert json.loads(output.read_text(encoding="utf-8"))["sources"] == ["empty.py"]


@pytest.mark.parametrize(
    ("paths", "language"),
    [
        (["missing.py"], None),
        (["."], "unknown"),
    ],
)
def test_cli_input_errors_exit_four(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    paths: list[str],
    language: str | None,
) -> None:
    args = [str(tmp_path / paths[0])] if paths[0] != "." else [str(tmp_path)]
    if language:
        args.extend(["--language", language])

    code, stdout, stderr = _invoke_cli(monkeypatch, capsys, *args)

    assert code == 4
    assert stdout == ""
    assert "error:" in stderr


def test_cli_empty_directory_exits_four(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, stdout, stderr = _invoke_cli(monkeypatch, capsys, str(tmp_path))

    assert code == 4
    assert stdout == ""
    assert "no Python or Rust source files" in stderr


def test_cli_missing_paths_exits_four(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, stdout, stderr = _invoke_cli(monkeypatch, capsys)

    assert code == 4
    assert stdout == ""
    assert "at least one input path is required" in stderr


def test_cli_repeated_runs_are_byte_identical(tmp_path: Path) -> None:
    source = _write(
        tmp_path / "sample.py",
        "def add(x):\n    return x\n"
        "def test_add():\n    assert add(2) == 2\n",
    )
    import subprocess

    command = [
        sys.executable,
        "-m",
        "agent",
        "harvest-tests",
        str(source),
    ]
    first = subprocess.run(command, capture_output=True, text=True, check=False)
    second = subprocess.run(command, capture_output=True, text=True, check=False)

    assert first.returncode == 0
    assert second.returncode == 0
    assert first.stdout == second.stdout
    assert json.loads(first.stdout)["sources"] == ["sample.py"]


def test_parse_error_in_single_file_is_not_an_input_error(tmp_path: Path) -> None:
    source = _write(tmp_path / "broken.py", "def test_broken(:\n")

    report = harvest_tests([source], None, None)

    assert report["totals"]["tests"] == 0
    assert report["skipped"][0]["reason"] == "parse_error"


def test_same_name_definitions_resolve_locally_and_report_ambiguity(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "sources"
    _write(
        source_root / "alpha.py",
        "def step(value):\n    return value\n"
        "def test_alpha():\n    assert step(1) == 1\n",
    )
    _write(
        source_root / "beta.py",
        "def step(left, right):\n    return left + right\n"
        "def test_beta():\n    assert step(2, 3) == 5\n",
    )
    _write(
        source_root / "gamma.py",
        "def test_gamma():\n    assert step(7) == 7\n",
    )

    report = harvest_tests([source_root], None, None)

    assert report["targets"]["step"] == {
        "python": {
            "params": None,
            "ambiguous": True,
            "definitions": [
                {"params": ["value"], "file": "alpha.py", "line": 1},
                {"params": ["left", "right"], "file": "beta.py", "line": 1},
            ],
        }
    }
    assert [item["args"] for item in report["observations"]] == [
        {"value": 1},
        {"left": 2, "right": 3},
        [7],
    ]


def test_python_only_harvests_direct_assertions_and_unconditional_with(
    tmp_path: Path,
) -> None:
    source = _write(
        tmp_path / "test_direct.py",
        "def f(x): return x\n"
        "def test_direct():\n"
        "    if False:\n        assert f(1) == 1\n"
        "    for _ in ():\n        assert f(2) == 2\n"
        "    while False:\n        assert f(3) == 3\n"
        "    try:\n        assert f(4) == 4\n"
        "    except AssertionError:\n        assert f(5) == 5\n"
        "    with open(__file__):\n        assert f(6) == 6\n",
    )
    report = _report(source)
    assert [item["args"] for item in report["observations"]] == [{"x": 6}]
    assert [item["reason"] for item in report["skipped"]] == [
        "conditional_assertion"
    ] * 5
    assert all({"file", "line", "test"} <= item.keys() for item in report["skipped"])


def test_python_assertions_after_return_and_raise_are_unreachable(tmp_path: Path) -> None:
    source = _write(
        tmp_path / "test_unreachable.py",
        "def f(x): return x\n"
        "def test_return():\n    return\n    assert f(1) == 1\n"
        "def test_raise():\n    raise RuntimeError()\n    assert f(2) == 2\n",
    )
    report = _report(source)
    assert report["observations"] == []
    assert [item["reason"] for item in report["skipped"]] == [
        "unreachable_assertion",
        "unreachable_assertion",
    ]


def test_python_exits_inside_nested_with_make_later_assertions_unreachable(
    tmp_path: Path,
) -> None:
    source = _write(
        tmp_path / "test_with_exit.py",
        "def f(x): return x\n"
        "def test_return_in_with():\n"
        "    with open(__file__):\n"
        "        return\n"
        "    assert f(1) == 1\n"
        "def test_raise_in_nested_with():\n"
        "    with open(__file__):\n"
        "        with open(__file__):\n"
        "            return\n"
        "            assert f(2) == 2\n"
        "        assert f(3) == 3\n"
        "    assert f(4) == 4\n",
    )

    report = _report(source)

    assert report["observations"] == []
    assert [item["reason"] for item in report["skipped"]] == [
        "unreachable_assertion",
        "unreachable_assertion",
        "unreachable_assertion",
        "unreachable_assertion",
    ]


def test_python_raise_inside_with_is_conditional_but_top_level_raise_is_unreachable(
    tmp_path: Path,
) -> None:
    source = _write(
        tmp_path / "test_raise_with.py",
        "import contextlib\n"
        "def f(x): return x\n"
        "def test_raise_with():\n"
        "    with contextlib.suppress(ValueError):\n"
        "        raise ValueError()\n"
        "        assert f(1) == 1\n"
        "    assert f(2) == 2\n"
        "def test_top_level_raise():\n"
        "    raise ValueError()\n"
        "    assert f(3) == 3\n",
    )

    report = _report(source)

    assert report["observations"] == []
    assert [item["reason"] for item in report["skipped"]] == [
        "conditional_assertion",
        "conditional_assertion",
        "unreachable_assertion",
    ]


@pytest.mark.parametrize(
    ("imports", "statement", "reason"),
    [
        ("import pytest\n", "pytest.fail('stop')", "unreachable_assertion"),
        (
            "from pytest import fail as stop\n",
            "stop('stop')",
            "unreachable_assertion",
        ),
        ("import pytest\n", "pytest.skip('stop')", "unreachable_assertion"),
        ("import pytest\n", "pytest.exit('stop')", "unreachable_assertion"),
        ("import sys\n", "sys.exit(0)", "unreachable_assertion"),
        ("from os import _exit as stop\n", "stop(0)", "unreachable_assertion"),
        (
            "import unittest\n",
            "raise unittest.SkipTest('stop')",
            "unreachable_assertion",
        ),
        (
            "from unittest import SkipTest\n",
            "raise SkipTest('stop')",
            "unreachable_assertion",
        ),
        (
            "import contextlib\nimport pytest\n",
            "with contextlib.suppress(BaseException):\n    pytest.fail('stop')",
            "conditional_assertion",
        ),
    ],
)
def test_python_terminating_calls_classify_later_assertions(
    tmp_path: Path, imports: str, statement: str, reason: str
) -> None:
    source = _write(
        tmp_path / "test_terminating.py",
        imports
        + "def f(x): return x\n"
        + "def test_terminating():\n"
        + "".join(f"    {line}\n" for line in statement.splitlines())
        + "    assert f(1) == 1\n",
    )

    report = _report(source)

    assert report["observations"] == []
    assert report["skipped"][0]["reason"] == reason


@pytest.mark.parametrize("call", ["self.fail('stop')", "self.skipTest('stop')"])
def test_python_unittest_terminating_methods_make_later_assertions_unreachable(
    tmp_path: Path, call: str
) -> None:
    source = _write(
        tmp_path / "test_unittest_terminating.py",
        "import unittest\n"
        "def f(x): return x\n"
        "class TestTerminating(unittest.TestCase):\n"
        "    def test_terminating(self):\n"
        f"        {call}\n"
        "        assert f(1) == 1\n",
    )

    report = _report(source)

    assert report["observations"] == []
    assert report["skipped"][0]["reason"] == "unreachable_assertion"


@pytest.mark.parametrize(
    "decorator",
    [
        "@pytest.mark.skip",
        "@pytest.mark.skipif(True, reason='skip')",
        "@pytest.mark.xfail",
        "@skip",
        "@skipif(True)",
        "@xfail",
        "@unittest.skip",
        "@unittest.skipIf(True, 'skip')",
        "@unittest.skipUnless(False, 'skip')",
        "@unittest.expectedFailure",
        "@skip_test",
        "@skip_if(True)",
        "@skip_unless(False)",
        "@expected_failure",
    ],
)
def test_python_skip_decorators_produce_one_not_run_skip(
    tmp_path: Path, decorator: str
) -> None:
    bare = decorator.startswith("@skip") or decorator.startswith("@xfail") or decorator.startswith("@expected")
    imports = (
        "from pytest.mark import skip, skipif, xfail\n"
        "from unittest import skip as skip_test, skipIf as skip_if, "
        "skipUnless as skip_unless, expectedFailure as expected_failure\n"
        if bare
        else "import pytest\nimport unittest\n"
    )
    source = _write(
        tmp_path / "test_skipped.py",
        imports
        + "def f(x): return x\n"
        + decorator
        + "\ndef test_skipped():\n    assert f(1) == 1\n",
    )
    report = _report(source)
    assert report["observations"] == []
    assert report["totals"]["tests"] == 1
    assert len(report["skipped"]) == 1
    assert report["skipped"][0]["reason"] == "test_not_run"
    assert report["skipped"][0]["line"] == len(imports.splitlines()) + 3


@pytest.mark.parametrize(
    ("imports", "decorator", "not_run"),
    [
        ("import pytest\n", "@pytest.mark.skipif(False, reason='skip')", False),
        ("import pytest\n", "@pytest.mark.skipif(True, reason='skip')", True),
        ("import pytest\n", "@pytest.mark.skipif(condition=False)", False),
        ("import pytest\n", "@pytest.mark.skipif(condition=True)", True),
        ("import pytest\n", "@pytest.mark.skipif(CONDITION)", True),
        ("import unittest\n", "@unittest.skipIf(False, 'skip')", False),
        ("import unittest\n", "@unittest.skipIf(True, 'skip')", True),
        ("import unittest\n", "@unittest.skipUnless(True, 'skip')", False),
        ("import unittest\n", "@unittest.skipUnless(False, 'skip')", True),
        (
            "from pytest.mark import skipif as skip_if\n",
            "@skip_if(False, reason='skip')",
            False,
        ),
        (
            "from unittest import skipIf as skip_if\n",
            "@skip_if(False, 'skip')",
            False,
        ),
        (
            "from unittest import skipUnless as skip_unless\n",
            "@skip_unless(True, 'skip')",
            False,
        ),
        (
            "from unittest import skipUnless as skip_unless\n",
            "@skip_unless(False, 'skip')",
            True,
        ),
    ],
)
def test_python_skip_conditions_only_skip_tests_not_known_to_run(
    tmp_path: Path, imports: str, decorator: str, not_run: bool
) -> None:
    source = _write(
        tmp_path / "test_skip_condition.py",
        imports
        + "def f(x): return x\n"
        + decorator
        + "\ndef test_condition():\n    assert f(1) == 1\n",
    )

    report = _report(source)

    assert bool(report["skipped"]) is not_run
    assert bool(report["observations"]) is (not not_run)
    if not_run:
        assert report["skipped"][0]["reason"] == "test_not_run"


def test_python_class_skip_and_import_bound_attribute_calls(tmp_path: Path) -> None:
    _write(tmp_path / "lib.py", "def f(x): return x\n")
    source = _write(
        tmp_path / "test_attrs.py",
        "import lib as imported\n"
        "from package import lib as package_lib\n"
        "import unittest\n"
        "@unittest.skip('skip class')\n"
        "class TestSkipped(unittest.TestCase):\n"
        "    def test_skip(self): assert imported.f(1) == 1\n"
        "def test_self_attr(self): assert self.f(1) == 1\n"
        "def test_object_attr(): assert obj.f(1) == 1\n"
        "def test_method_target(): assert c.g(1) == 1\n"
        "def test_module_attr(): assert imported.f(2) == 2\n"
        "def test_alias_attr(): assert package_lib.f(3) == 3\n",
    )
    report = harvest_tests([tmp_path], None, None)
    assert [item["test"] for item in report["observations"]] == [
        "test_module_attr",
        "test_alias_attr",
    ]
    assert [item["reason"] for item in report["skipped"]].count("test_not_run") == 1
    assert all(item["reason"] == "no_target_call" for item in report["skipped"] if item["test"] in {"test_self_attr", "test_object_attr", "test_method_target"})
    filtered = harvest_tests([source], None, {"f"})
    assert any(item["test"] == "test_self_attr" and item["reason"] == "no_target_call" for item in filtered["skipped"])


def test_python_imported_class_attribute_is_not_a_module_target(tmp_path: Path) -> None:
    _write(tmp_path / "lib.py", "def f(value): return value\n")
    source = _write(
        tmp_path / "test_service.py",
        "import lib\n"
        "from lib import Service\n"
        "def test_service():\n"
        "    assert Service.f(1) == 1\n"
        "    assert lib.f(2) == 2\n",
    )

    report = harvest_tests([source.parent], None, None)

    assert [item["target"] for item in report["observations"]] == ["f"]
    assert report["skipped"][0]["reason"] == "no_target_call"
    assert report["skipped"][0]["test"] == "test_service"


def test_python_attribute_targets_require_unshadowed_module_roots(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "pkg" / "module.py", "def f(value): return value\n")
    _write(
        tmp_path / "pkg" / "package_module" / "__init__.py",
        "def g(value): return value\n",
    )
    _write(tmp_path / "lib.py", "def h(value): return value\n")
    source = _write(
        tmp_path / "test_roots.py",
        "from pkg import module as imported_module\n"
        "from pkg import package_module\n"
        "from pkg import Service\n"
        "import pkg.module\n"
        "import lib as root\n"
        "def test_modules():\n"
        "    assert imported_module.f(1) == 1\n"
        "    assert package_module.g(2) == 2\n"
        "    assert pkg.module.f(3) == 3\n"
        "    assert Service.f(4) == 4\n"
        "def test_rebound():\n"
        "    root = object()\n"
        "    assert root.h(5) == 5\n"
        "def test_nested_rebound():\n"
        "    def helper():\n"
        "        root = object()\n"
        "    assert root.h(6) == 6\n"
        "def test_local_import():\n"
        "    import lib as local_root\n"
        "    assert local_root.h(8) == 8\n"
        "def test_unshadowed():\n"
        "    assert root.h(7) == 7\n",
    )

    report = harvest_tests([tmp_path], None, None)

    assert [item["test"] for item in report["observations"]] == [
        "test_modules",
        "test_modules",
        "test_modules",
        "test_nested_rebound",
        "test_local_import",
        "test_unshadowed",
    ]
    assert [item["target"] for item in report["observations"]] == [
        "f",
        "g",
        "f",
        "h",
        "h",
        "h",
    ]
    assert [
        (item["test"], item["reason"]) for item in report["skipped"]
    ] == [
        ("test_modules", "no_target_call"),
        ("test_rebound", "no_target_call"),
    ]


def test_rust_direct_conditional_unreachable_and_ignored_assertions(
    tmp_path: Path,
) -> None:
    source = _write(
        tmp_path / "rust.rs",
        "fn f(x: i64) -> i64 { x }\n"
        "#[cfg(test)] mod tests { use super::*;\n"
        "#[test] fn test_control() { if false { assert_eq!(f(1), 1); } "
        "match 1 { _ => { assert_eq!(f(2), 2); } } "
        "loop { assert_eq!(f(3), 3); break; } "
        "while false { assert_eq!(f(4), 4); } "
        "for _ in 0..1 { assert_eq!(f(5), 5); } "
        "{ assert_eq!(f(6), 6); } assert_eq!(f(7), 7); }\n"
        "#[test] fn test_unreachable() { panic!(\"stop\"); assert_eq!(f(8), 8); }\n"
        "#[test] #[ignore] fn test_ignored() { assert_eq!(f(9), 9); }\n"
        "}",
    )
    report = _report(source)
    assert [item["args"] for item in report["observations"]] == [{"x": 7}]
    assert [item["reason"] for item in report["skipped"]].count("conditional_assertion") == 6
    assert any(item["reason"] == "unreachable_assertion" for item in report["skipped"])
    assert sum(item["reason"] == "test_not_run" for item in report["skipped"]) == 1


@pytest.mark.parametrize("terminal", ["return;", "panic!(\"x\");", "unreachable!();", "todo!();", "unimplemented!();"])
def test_rust_assertions_after_terminal_are_unreachable(
    tmp_path: Path, terminal: str
) -> None:
    source = _rust_file(
        tmp_path,
        f"{terminal} assert_eq!(add(1, 2), 3);",
    )
    report = _report(source)
    assert report["observations"] == []
    assert report["skipped"][0]["reason"] == "unreachable_assertion"


@pytest.mark.parametrize("exit_call", ["std::process::exit(1)", "process::exit(1)"])
def test_rust_process_exit_makes_later_assertions_unreachable(
    tmp_path: Path, exit_call: str
) -> None:
    source = _rust_file(
        tmp_path,
        f"{exit_call}; assert_eq!(add(1, 2), 3);",
    )

    report = _report(source)

    assert report["observations"] == []
    assert report["skipped"][0]["reason"] == "unreachable_assertion"


def test_rust_question_mark_makes_later_assertions_conditional(
    tmp_path: Path,
) -> None:
    source = _write(
        tmp_path / "test_question.rs",
        "fn f(value: i64) -> i64 { value }\n"
        "#[test]\n"
        "fn test_question() -> Result<(), String> {\n"
        "    let _ = Err::<(), String>(\"early\")?;\n"
        "    assert_eq!(f(1), 1);\n"
        "    Ok(())\n"
        "}\n"
        "#[test]\n"
        "fn test_closure_question() {\n"
        "    let closure = || { let _ = Err::<(), String>(\"closure\")?; };\n"
        "    assert_eq!(f(2), 2);\n"
        "}\n",
    )

    report = _report(source)

    assert [item["args"] for item in report["observations"]] == [{"value": 2}]
    conditional = [
        item for item in report["skipped"]
        if item["test"] == "test_question"
    ]
    assert [item["reason"] for item in conditional] == ["conditional_assertion"]


def test_rust_async_blocks_do_not_contribute_assertions_or_exits(
    tmp_path: Path,
) -> None:
    source = _write(
        tmp_path / "test_async_block.rs",
        "fn f(value: i64) -> i64 { value }\n"
        "#[test]\n"
        "fn test_async_block() {\n"
        "    let _future = async {\n"
        "        assert_eq!(f(1), 1);\n"
        "        panic!(\"not executed here\");\n"
        "        let _ = Err::<(), String>(\"not executed here\")?;\n"
        "        assert_eq!(f(3), 3);\n"
        "    };\n"
        "    assert_eq!(f(2), 2);\n"
        "}\n",
    )

    report = _report(source)

    assert [item["args"] for item in report["observations"]] == [{"value": 2}]
    assert report["skipped"] == []


def test_should_panic_conditional_call_remains_ambiguous(tmp_path: Path) -> None:
    source = _write(
        tmp_path / "should_panic.rs",
        "fn fail(x: i64) { let _ = x; }\n#[cfg(test)] mod tests { use super::*;\n"
        "#[test] #[should_panic] fn test_reject() { if true { fail(1); } }\n}",
    )
    report = _report(source)
    assert report["observations"] == []
    assert report["skipped"][0]["reason"] == "ambiguous_rejects"


def test_rust_return_in_closure_does_not_hide_following_assertion(
    tmp_path: Path,
) -> None:
    source = _rust_file(
        tmp_path,
        "let closure = || { return; }; assert_eq!(add(1, 2), 3);",
    )
    report = _report(source)
    assert [item["kind"] for item in report["observations"]] == ["example"]


@pytest.mark.parametrize("language", ["python", "rust"])
def test_integer_literals_obey_i64_range(tmp_path: Path, language: str) -> None:
    if language == "python":
        cases = [
            ("assert add(9223372036854775807, 0) == 9223372036854775807", True),
            ("assert add(-9223372036854775808, 0) == -9223372036854775808", True),
            ("assert add(9223372036854775808, 0) == 0", False),
            ("assert add(999999999999999999999999999999999999999999999999, 0) == 0", False),
            ("assert add(-9223372036854775809, 0) == 0", False),
            ("assert add(1, 0) < 9223372036854775808", False),
        ]
    else:
        cases = [
            ("assert_eq!(add(9223372036854775807i64, 0), 9223372036854775807i64);", True),
            ("assert_eq!(add(-9223372036854775808i64, 0), -9223372036854775808i64);", True),
            ("assert_eq!(add(9223372036854775808i64, 0), 0);", False),
            ("assert_eq!(add(999999999999999999999999999999999999999, 0), 0);", False),
            ("assert_eq!(add(-9223372036854775809i64, 0), 0);", False),
            ("assert!(add(1, 0) < 9223372036854775808);", False),
        ]
    accepted = []
    for index, (assertion, valid) in enumerate(cases):
        path = _python_file(tmp_path, assertion) if language == "python" else _rust_file(tmp_path, assertion)
        if index:
            path = _write(path, path.read_text())
        report = _report(path)
        accepted.append(bool(report["observations"]))
        if not valid:
            assert report["skipped"][0]["reason"] == "unsupported_expression"
    assert accepted == [valid for _, valid in cases]


def test_unique_definition_in_another_input_file_resolves_call(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "sources"
    _write(source_root / "lib.py", "def step(value):\n    return value\n")
    _write(
        source_root / "test_step.py",
        "def test_step():\n    assert step(3) == 3\n",
    )

    report = harvest_tests([source_root], None, None)

    assert report["targets"]["step"] == {
        "python": {"params": ["value"], "file": "lib.py", "line": 1}
    }
    assert report["observations"][0]["args"] == {"value": 3}


def test_mixed_language_definitions_resolve_and_report_per_language(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "lib.py", "def f(amount):\n    return amount + 1\n")
    _write(tmp_path / "python_test.py", "def test_python():\n    assert f(2) == 3\n")
    _write(
        tmp_path / "lib_test.rs",
        "fn f(value: i64) -> i64 { value + 1 }\n"
        "#[test]\n"
        "fn test_rust() { assert_eq!(f(3), 4); }\n",
    )

    report = harvest_tests([tmp_path], None, None)

    assert report["targets"]["f"] == {
        "python": {"params": ["amount"], "file": "lib.py", "line": 1},
        "rust": {"params": ["value"], "file": "lib_test.rs", "line": 1},
    }
    assert [item["args"] for item in report["observations"]] == [
        {"value": 3},
        {"amount": 2},
    ]


def test_python_imported_targets_are_selected_without_definitions(
    tmp_path: Path,
) -> None:
    source = _write(
        tmp_path / "test_imports.py",
        "from mathlib import plus as imported_plus\n"
        "import helpers as helper_module\n"
        "def test_imports():\n"
        "    assert imported_plus(1, 2) == 3\n"
        "    assert helper_module.bump(4) == 5\n",
    )

    report = _report(source)

    assert report["targets"] == {
        "bump": {"python": {"params": None, "file": None, "line": None}},
        "imported_plus": {"python": {"params": None, "file": None, "line": None}},
    }
    assert [item["target"] for item in report["observations"]] == [
        "imported_plus",
        "bump",
    ]
    assert [item["args"] for item in report["observations"]] == [[1, 2], [4]]


def test_python_imported_callable_targets_are_selected_in_raises_forms(
    tmp_path: Path,
) -> None:
    source = _write(
        tmp_path / "test_imported_raises.py",
        "from service import explode\n"
        "def test_imported_raises():\n"
        "    pytest.raises(ValueError, explode, 1)\n"
        "    self.assertRaises(ValueError, explode, 2)\n",
    )

    report = _report(source)

    assert report["targets"]["explode"] == {
        "python": {"params": None, "file": None, "line": None}
    }
    assert [item["kind"] for item in report["observations"]] == [
        "rejects",
        "rejects",
    ]
    assert [item["args"] for item in report["observations"]] == [[1], [2]]


def test_rust_imported_and_qualified_targets_are_selected(
    tmp_path: Path,
) -> None:
    source = _write(
        tmp_path / "test_imports.rs",
        "use service::direct;\n"
        "use service::{grouped, unused};\n"
        "#[test]\n"
        "fn test_imports() {\n"
        "    assert_eq!(direct(1), 1);\n"
        "    assert_eq!(grouped(2), 2);\n"
        "    assert_eq!(super::helper(3), 3);\n"
        "    assert_eq!(crate::module::qualified(4), 4);\n"
        "    assert_eq!(module::nested(5), 5);\n"
        "    assert_eq!(std::cmp::max(1, 2), 2);\n"
        "    std::assert_eq!(outside(6), 6);\n"
        "}\n",
    )

    report = _report(source)

    assert set(report["targets"]) == {
        "direct",
        "grouped",
        "helper",
        "qualified",
        "nested",
    }
    assert [item["target"] for item in report["observations"]] == [
        "direct",
        "grouped",
        "helper",
        "qualified",
        "nested",
    ]
    assert all(item["args"] == [index] for index, item in enumerate(report["observations"], 1))


@pytest.mark.parametrize(
    ("assertion", "kind"),
    [
        ("self.assertEqual(add(2, 3), 5, 'message')", "example"),
        ("self.assertEqual(add(2, 3), 5, msg='message')", "example"),
        ("self.assertNotEqual(add(2, 3), 5, 'message')", "relation"),
        ("self.assertNotEqual(add(2, 3), 5, msg='message')", "relation"),
        ("self.assertTrue(add(2, 3) > 0, 'message')", "relation"),
        ("self.assertTrue(add(2, 3) > 0, msg='message')", "relation"),
        ("self.assertFalse(add(2, 3) == 5, 'message')", "relation"),
        ("self.assertFalse(add(2, 3) == 5, msg='message')", "relation"),
        ("self.assertLess(add(2, 3), 5, 'message')", "relation"),
        ("self.assertLess(add(2, 3), 5, msg='message')", "relation"),
        ("self.assertLessEqual(add(2, 3), 5, 'message')", "relation"),
        ("self.assertLessEqual(add(2, 3), 5, msg='message')", "relation"),
        ("self.assertGreater(add(2, 3), 5, 'message')", "relation"),
        ("self.assertGreater(add(2, 3), 5, msg='message')", "relation"),
        ("self.assertGreaterEqual(add(2, 3), 5, 'message')", "relation"),
        ("self.assertGreaterEqual(add(2, 3), 5, msg='message')", "relation"),
    ],
)
def test_python_unittest_assertion_messages_are_ignored(
    tmp_path: Path, assertion: str, kind: str
) -> None:
    report = _report(_python_file(tmp_path, assertion))

    assert report["observations"][0]["kind"] == kind
    assert report["skipped"] == []


@pytest.mark.parametrize(
    "assertion",
    [
        "self.assertEqual(f(1), 1, 'msg')",
        "self.assertEqual(f(1), 1, msg='msg')",
    ],
)
def test_python_one_argument_assert_equal_messages_are_ignored(
    tmp_path: Path, assertion: str
) -> None:
    source = _write(
        tmp_path / "test_assert_equal_message.py",
        "def f(value):\n    return value\n"
        "class TestF:\n"
        "    def test_f(self):\n"
        f"        {assertion}\n",
    )

    report = _report(source)

    assert report["observations"][0]["args"] == {"value": 1}
    assert report["observations"][0]["result"] == 1


def test_python_assert_statement_message_is_ignored(tmp_path: Path) -> None:
    report = _report(_python_file(tmp_path, "assert add(2, 3) == 5, 'message'"))

    assert report["observations"][0]["kind"] == "example"
    assert report["observations"][0]["result"] == 5


@pytest.mark.parametrize(
    "assertion",
    [
        "with pytest.raises(AssertionError):\n    assert add(1, 2) == 3",
        "with self.assertRaises(AssertionError):\n    self.assertEqual(add(1, 2), 3)",
    ],
)
def test_assertions_inside_raises_contexts_are_ambiguous(
    tmp_path: Path, assertion: str
) -> None:
    source = _write(
        tmp_path / "test_raises.py",
        "def add(left, right):\n    return left + right\n"
        "def test_raises():\n"
        + "".join(f"    {line}\n" for line in assertion.splitlines()),
    )

    report = _report(source)

    assert report["observations"] == []
    assert report["skipped"][0]["reason"] == "ambiguous_rejects"


def test_python_nested_helper_scopes_are_not_harvested(tmp_path: Path) -> None:
    source = _write(
        tmp_path / "test_nested.py",
        "def add(value):\n    return value\n"
        "def test_nested():\n"
        "    value = 1\n"
        "    def helper():\n"
        "        value = 2\n"
        "        assert add(2) == 2\n"
        "    class Nested:\n"
        "        def check(self):\n"
        "            assert add(3) == 3\n"
        "    callback = lambda: add(4)\n"
        "    assert add(value) == 1\n",
    )

    report = _report(source)

    assert len(report["observations"]) == 1
    assert report["observations"][0]["args"] == {"value": 1}


def test_rust_nested_helper_scopes_are_not_harvested(tmp_path: Path) -> None:
    source = _rust_file(
        tmp_path,
        "fn helper() { assert_eq!(add(2, 3), 5); }\n"
        "let mut left = 1;\n"
        "let closure = || { assert_eq!(add(4, 5), 9); };\n"
        "assert_eq!(add(left, 2), 3);",
    )

    report = _report(source)

    assert len(report["observations"]) == 1
    assert report["observations"][0]["args"] == {"left": 1, "right": 2}
    assert report["skipped"] == []


@pytest.mark.parametrize(
    "write",
    [
        "value = 2",
        "value += 1",
        "def value(): pass",
        "class value: pass",
        "import replacement as value",
        "for value in (): pass",
        "with open(__file__) as value: pass",
    ],
)
def test_python_nested_nonlocal_writes_invalidate_literal_bindings(
    tmp_path: Path, write: str
) -> None:
    source = _write(
        tmp_path / "test_nested_write.py",
        "def identity(value):\n    return value\n"
        "def test_nested_write():\n"
        "    value = 1\n"
        "    def helper():\n"
        "        nonlocal value\n"
        f"        {write}\n"
        "    assert identity(value) == 1\n",
    )

    report = _report(source)

    assert report["observations"] == []
    assert report["skipped"][0]["reason"] == "non_literal_argument"


def test_python_nested_local_writes_do_not_shadow_outer_bindings_or_roots(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "lib.py", "def f(value):\n    return value + 1\n")
    source = _write(
        tmp_path / "test_nested_local.py",
        "import lib as root\n"
        "from lib import f\n"
        "def test_nested_local():\n"
        "    value = 3\n"
        "    def helper(root, value, f):\n"
        "        root = object()\n"
        "        value = 4\n"
        "        f = object()\n"
        "    assert f(value) == 4\n"
        "    assert root.f(1) == 2\n",
    )

    report = harvest_tests([source.parent], None, None)

    assert [item["args"] for item in report["observations"]] == [
        {"value": 3},
        {"value": 1},
    ]


@pytest.mark.parametrize(
    "write",
    [
        "def root(): pass",
        "class root: pass",
        "import replacement as root",
        "for root in (): pass",
        "with open(__file__) as root: pass",
    ],
)
def test_python_nested_global_bindings_invalidate_import_root(
    tmp_path: Path, write: str
) -> None:
    _write(tmp_path / "lib.py", "def f(value):\n    return value + 1\n")
    source = _write(
        tmp_path / "test_nested_global.py",
        "import lib as root\n"
        "def test_nested_global():\n"
        "    def helper():\n"
        "        global root\n"
        f"        {write}\n"
        "    assert root.f(1) == 2\n",
    )

    report = harvest_tests([source.parent], None, None)

    assert report["observations"] == []
    assert report["skipped"][0]["reason"] == "no_target_call"


def test_python_nested_nonlocal_write_invalidates_import_root(tmp_path: Path) -> None:
    _write(tmp_path / "lib.py", "def f(value):\n    return value + 1\n")
    source = _write(
        tmp_path / "test_nested_nonlocal.py",
        "def test_nested_nonlocal():\n"
        "    import lib as root\n"
        "    def helper():\n"
        "        nonlocal root\n"
        "        root = object()\n"
        "    assert root.f(1) == 2\n",
    )

    report = harvest_tests([source.parent], None, None)

    assert report["observations"] == []
    assert report["skipped"][0]["reason"] == "no_target_call"


@pytest.mark.parametrize("write", ["value = 2", "value += 1"])
def test_rust_nested_closure_writes_invalidate_literal_bindings(
    tmp_path: Path, write: str
) -> None:
    source = _write(
        tmp_path / "test_nested_write.rs",
        "fn identity(value: i64) -> i64 { value }\n"
        "#[test]\n"
        "fn test_nested_write() {\n"
        "    let mut value = 1;\n"
        f"    let closure = || {{ {write}; }};\n"
        "    assert_eq!(identity(value), 1);\n"
        "}\n",
    )

    report = _report(source)

    assert report["observations"] == []
    assert report["skipped"][0]["reason"] == "non_literal_argument"


@pytest.mark.parametrize(
    "async_block",
    ["async { x = 9; }", "async move { x = 9; }"],
)
def test_rust_async_block_writes_invalidate_literal_bindings(
    tmp_path: Path, async_block: str
) -> None:
    source = _write(
        tmp_path / "test_async_write.rs",
        "fn f(value: i64) -> i64 { value + 1 }\n"
        "#[test]\n"
        "fn test_async_write() {\n"
        "    let mut x = 3;\n"
        f"    block_on({async_block});\n"
        "    assert_eq!(f(x), 4);\n"
        "}\n",
    )

    report = _report(source)

    assert report["observations"] == []
    assert report["skipped"][0]["reason"] == "non_literal_argument"


@pytest.mark.parametrize(
    "closure",
    [
        "let closure = || { let mut value = 2; value = 3; };",
        "let closure = |mut value: i64| { value = 2; };",
    ],
)
def test_rust_closure_local_writes_do_not_invalidate_outer_binding(
    tmp_path: Path, closure: str
) -> None:
    source = _write(
        tmp_path / "test_closure_local.rs",
        "fn identity(value: i64) -> i64 { value }\n"
        "#[test]\n"
        "fn test_closure_local() {\n"
        "    let value = 1;\n"
        f"    {closure}\n"
        "    assert_eq!(identity(value), 1);\n"
        "}\n",
    )

    report = _report(source)

    assert report["observations"][0]["args"] == {"value": 1}


@pytest.mark.parametrize(
    "body",
    [
        'assert_eq!(add(1, 2), 3);',
        'panic!("other panic");',
        "other_macro!(add(1, 2));",
    ],
)
def test_rust_should_panic_rejects_other_body_statements_as_ambiguous(
    tmp_path: Path, body: str
) -> None:
    source = _write(
        tmp_path / "test_should_panic.rs",
        "fn add(left: i64, right: i64) -> i64 { left + right }\n"
        "#[test]\n"
        "#[should_panic]\n"
        "fn test_rejects() {\n"
        f"    {body}\n"
        "}\n",
    )

    report = _report(source)

    assert report["observations"] == []
    assert report["skipped"][0]["reason"] == "ambiguous_rejects"


def test_rust_should_panic_accepts_ignored_call_after_literal_bindings(
    tmp_path: Path,
) -> None:
    source = _write(
        tmp_path / "test_should_panic.rs",
        "fn add(left: i64, right: i64) -> i64 { left + right }\n"
        "#[test]\n"
        "#[should_panic]\n"
        "fn test_rejects() {\n"
        "    let left: i64 = 1;\n"
        "    let _ = add(left, 2);\n"
        "}\n",
    )

    report = _report(source)

    assert report["observations"][0]["kind"] == "rejects"
    assert report["observations"][0]["args"] == {"left": 1, "right": 2}


def test_rust_should_panic_accepts_tail_call_expression(tmp_path: Path) -> None:
    source = _write(
        tmp_path / "test_tail_reject.rs",
        "fn fail(value: i64) { panic!(\"failure\"); }\n"
        "#[test]\n"
        "#[should_panic]\n"
        "fn test_fail() { fail(1) }\n",
    )

    report = _report(source)

    assert report["observations"][0]["kind"] == "rejects"
    assert report["observations"][0]["args"] == {"value": 1}


def test_rust_assert_macros_ignore_trailing_format_arguments(
    tmp_path: Path,
) -> None:
    source = _rust_file(
        tmp_path,
        'assert_eq!(add(2, 3), 5, "message {}", add(9, 9));\n'
        'assert_ne!(add(2, 3), 0, "message {}", add(9, 9));\n'
        'assert!(add(2, 3) > 0, "message {}", add(9, 9));',
    )

    report = _report(source)

    assert [item["kind"] for item in report["observations"]] == [
        "example",
        "relation",
        "relation",
    ]
    assert [item["args"] for item in report["observations"]] == [
        {"left": 2, "right": 3},
        {"left": 2, "right": 3},
        {"left": 2, "right": 3},
    ]


def test_rust_single_argument_assertions_ignore_format_messages(
    tmp_path: Path,
) -> None:
    source = _write(
        tmp_path / "test_single_argument_messages.rs",
        "fn f(value: i64) -> i64 { value }\n"
        "#[test]\n"
        "fn test_messages() {\n"
        '    assert_eq!(f(1), 1, "msg {}", f(2));\n'
        '    assert!(f(1) > 0, "msg");\n'
        "}\n",
    )

    report = _report(source)

    assert [item["kind"] for item in report["observations"]] == [
        "example",
        "relation",
    ]
    assert [item["args"] for item in report["observations"]] == [
        {"value": 1},
        {"value": 1},
    ]


def test_cli_all_parse_errors_exit_four_but_partial_parse_errors_succeed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    broken = _write(tmp_path / "broken.py", "def broken(:\n")

    code, stdout, stderr = _invoke_cli(monkeypatch, capsys, str(broken))

    assert code == 4
    assert stdout == ""
    assert "no source files could be parsed" in stderr

    source_root = tmp_path / "mixed"
    _write(source_root / "broken.py", "def broken(:\n")
    _write(
        source_root / "valid.py",
        "def add(value):\n    return value\n"
        "def test_add():\n    assert add(2) == 2\n",
    )

    code, stdout, stderr = _invoke_cli(monkeypatch, capsys, str(source_root))

    assert code == 0
    assert stderr == ""
    assert len(json.loads(stdout)["observations"]) == 1
    assert "parse_error" in stdout


def test_rust_source_is_parsed_once_for_multiple_tests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _write(
        tmp_path / "math.rs",
        "fn add(value: i64) -> i64 { value }\n"
        "#[test]\nfn test_first() { assert_eq!(add(1), 1); }\n"
        "#[test]\nfn test_second() { assert_eq!(add(2), 2); }\n",
    )
    original_parse = test_harvest.tree_sitter_extract.parse
    parse_count = 0

    def counted_parse(source_text: str, language: str):
        nonlocal parse_count
        parse_count += 1
        return original_parse(source_text, language)

    monkeypatch.setattr(test_harvest.tree_sitter_extract, "parse", counted_parse)

    report = _report(source)

    assert parse_count == 1
    assert len(report["observations"]) == 2
