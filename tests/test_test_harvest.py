from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from agent.__main__ import main as agent_cli_main
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
        prelude="class module:\n    pass\n",
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

    observation = _report(source)["observations"][0]

    assert observation["target"] == "increment"
    assert observation["args"] == {"value": 2}


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
        ("panic!(\"expected\");", "no_target_call"),
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
        "params": None,
        "file": None,
        "line": None,
    }
    assert missing["observations"][0]["args"] == [2]


def test_python_module_attribute_calls_resolve_by_last_component(
    tmp_path: Path,
) -> None:
    source = _write(
        tmp_path / "test_module.py",
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
