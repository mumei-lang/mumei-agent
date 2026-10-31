from __future__ import annotations

import copy
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.code_to_spec import CodeToSpecExtractor
from agent.extract_spec import (
    build_parser,
    extract_spec_from_code_directory,
    main,
)
from agent.test_harvest import HarvestInputError


SPEC = {
    "task_id": "observed-add",
    "target_file": "std/math/add.mm",
    "mode": "create",
    "atoms": [
        {
            "name": "add",
            "description": "Add two integers.",
            "inputs": [
                {"name": "a", "type": "i64"},
                {"name": "b", "type": "i64"},
            ],
            "return_type": "i64",
            "requires": "true",
            "ensures": "result == a + b",
            "effects": [],
        }
    ],
}
HARVEST = {
    "schema": "mumei.test-harvest/v1",
    "targets": {"add": {"python": {"params": ["a", "b"]}}},
    "observations": [
        {
            "kind": "example",
            "target": "add",
            "args": {"a": 2, "b": 3},
            "result": 5,
            "test": "test_add",
            "file": "test_add.py",
            "line": 4,
        }
    ],
}


class FakeMumei:
    def __init__(self, verdicts: list[str] | None = None) -> None:
        self.verdicts = list(verdicts or ["consistent"])
        self.calls: list[tuple[str, dict]] = []

    def observe_check(self, module_path: str, harvest_path: str):
        module = Path(module_path)
        harvest = json.loads(Path(harvest_path).read_text(encoding="utf-8"))
        assert module.is_file()
        assert harvest["schema"] == "mumei.test-harvest/v1"
        verdict = (
            self.verdicts.pop(0)
            if len(self.verdicts) > 1
            else self.verdicts[0]
        )
        self.calls.append((module.read_text(encoding="utf-8"), harvest))
        return {
            "returncode": int(verdict in {"contradicts_ensures", "requires_admits_rejected"}),
            "report": {
                "schema": "mumei.observation-check/v1",
                "results": [
                    {
                        "kind": "example",
                        "target": "add",
                        "test": "test_add",
                        "file": "test_add.py",
                        "line": 4,
                        "args": [2, 3],
                        "result": 5,
                        "verdict": verdict,
                        "detail": "observation detail",
                    }
                ],
                "totals": {
                    "consistent": int(verdict == "consistent"),
                    "contradicts_ensures": int(verdict == "contradicts_ensures"),
                    "outside_requires": 0,
                    "not_checked": 0,
                },
            },
            "stderr": "",
        }


def _config() -> MagicMock:
    config = MagicMock()
    config.model = "test-model"
    config.max_retries = 2
    config.mumei_bin = "mumei"
    config.create_client.return_value = MagicMock()
    return config


def _response_for_spec(spec: dict) -> MagicMock:
    response = MagicMock()
    response.choices = [
        MagicMock(message=MagicMock(content=json.dumps(spec)))
    ]
    return response


def _llm_client(*specs: dict) -> MagicMock:
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _response_for_spec(spec) for spec in specs
    ]
    return client


def _args(tmp_path: Path, *options: str):
    return build_parser().parse_args(
        [
            "--text",
            "Add two integers.",
            *options,
            "--output",
            str(tmp_path / "spec.json"),
        ]
    )


def _call_checker_from_fake_extractor(spec: dict, kwargs: dict) -> dict:
    kwargs["spec_checker"](spec)
    return spec


def test_extract_spec_from_tests_text_passes_context_and_writes_report(
    tmp_path: Path,
    capsys,
) -> None:
    report_path = tmp_path / "observations.json"
    args = _args(
        tmp_path,
        "--from-tests",
        str(tmp_path / "tests"),
        "--from-tests-language",
        "python",
        "--observations-output",
        str(report_path),
    )
    mumei = FakeMumei()
    config = _config()
    with (
        patch("agent.extract_spec.AgentConfig", return_value=config),
        patch("agent.extract_spec.create_mumei_client", return_value=mumei),
        patch("agent.extract_spec.harvest_tests", return_value=HARVEST) as harvest,
        patch(
            "agent.extract_spec.extract_spec",
            side_effect=lambda *pos, **kwargs: _call_checker_from_fake_extractor(
                SPEC, kwargs
            ),
        ) as extract,
    ):
        main(args)

    harvest.assert_called_once()
    assert harvest.call_args.args[1] == "python"
    assert extract.call_args.kwargs["spec_checker"] is not None
    assert "# Observed test behavior" in extract.call_args.kwargs["extra_context"]
    assert len(mumei.calls) == 1
    assert json.loads(report_path.read_text(encoding="utf-8"))["schema"] == (
        "mumei.observation-check/v1"
    )
    captured = capsys.readouterr()
    assert "Observation checks:" in captured.err
    assert "outside_requires=0 not_checked=0" in captured.err


def test_extract_spec_from_tests_retries_inconclusive_observations(
    tmp_path: Path,
) -> None:
    retried_spec = copy.deepcopy(SPEC)
    retried_spec["atoms"][0]["requires"] = "a >= 0 && b >= 0"
    args = _args(
        tmp_path,
        "--from-tests",
        str(tmp_path / "tests"),
        "--max-retries",
        "2",
    )
    mumei = FakeMumei(["inconclusive", "consistent"])
    config = _config()
    client = _llm_client(SPEC, retried_spec)
    config.create_client.return_value = client
    with (
        patch("agent.extract_spec.AgentConfig", return_value=config),
        patch("agent.extract_spec.create_mumei_client", return_value=mumei),
        patch("agent.extract_spec.harvest_tests", return_value=HARVEST),
    ):
        main(args)

    assert json.loads((tmp_path / "spec.json").read_text(encoding="utf-8")) == (
        retried_spec
    )
    assert client.chat.completions.create.call_count == 2
    retry_prompt = client.chat.completions.create.call_args_list[1].kwargs[
        "messages"
    ][1]["content"]
    assert (
        "test test_add (test_add.py:4) observed add(2, 3) == 5, but mumei "
        "observe could not decide it against atom add's contract (detail: "
        "observation detail); use only parameters, literals, and Mumei "
        "arithmetic, comparison, and logical operators, with result only in "
        "ensures"
    ) in retry_prompt


@pytest.mark.parametrize(
    ("verdict", "warning"),
    [
        ("inconclusive", "could not decide it (detail: observation detail)"),
        ("outside_requires", "atom add's requires excludes these arguments"),
    ],
)
def test_extract_spec_from_tests_warns_on_final_soft_observation(
    verdict: str,
    warning: str,
    tmp_path: Path,
    capsys,
) -> None:
    args = _args(
        tmp_path,
        "--from-tests",
        str(tmp_path / "tests"),
        "--max-retries",
        "1",
    )
    config = _config()
    config.create_client.return_value = _llm_client(SPEC)
    with (
        patch("agent.extract_spec.AgentConfig", return_value=config),
        patch(
            "agent.extract_spec.create_mumei_client",
            return_value=FakeMumei([verdict]),
        ),
        patch("agent.extract_spec.harvest_tests", return_value=HARVEST),
    ):
        main(args)

    assert json.loads((tmp_path / "spec.json").read_text(encoding="utf-8")) == SPEC
    stderr = capsys.readouterr().err
    assert "Warning: test test_add (test_add.py:4) observed add(2, 3) == 5, " in (
        stderr
    )
    assert warning in stderr
    assert "Error:" not in stderr


@pytest.mark.parametrize(
    ("language", "expected_file", "expected_line"),
    [
        ("python", "test_add.py", 5),
        ("rust", "test_add.rs", 7),
    ],
)
def test_extract_spec_from_tests_harvests_real_observations(
    language: str,
    expected_file: str,
    expected_line: int,
    tmp_path: Path,
) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_add.py").write_text(
        "def add(left, right):\n"
        "    return left + right\n"
        "\n"
        "def test_add():\n"
        "    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    (tests_dir / "test_add.rs").write_text(
        "fn add(left: i64, right: i64) -> i64 { left + right }\n"
        "#[cfg(test)]\n"
        "mod tests {\n"
        "    use super::*;\n"
        "    #[test]\n"
        "    fn test_add() {\n"
        "        assert_eq!(add(2, 3), 5);\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    args = _args(
        tmp_path,
        "--from-tests",
        str(tests_dir),
        "--from-tests-language",
        language,
    )
    mumei = FakeMumei()
    with (
        patch("agent.extract_spec.AgentConfig", return_value=_config()),
        patch("agent.extract_spec.create_mumei_client", return_value=mumei),
        patch(
            "agent.extract_spec.extract_spec",
            side_effect=lambda *pos, **kwargs: _call_checker_from_fake_extractor(
                SPEC, kwargs
            ),
        ),
    ):
        main(args)

    assert len(mumei.calls) == 1
    harvest = mumei.calls[0][1]
    assert set(harvest["targets"]["add"]) == {language}
    assert len(harvest["observations"]) == 1
    observation = harvest["observations"][0]
    assert {
        "kind": observation["kind"],
        "target": observation["target"],
        "test": observation["test"],
        "file": observation["file"],
        "line": observation["line"],
    } == {
        "kind": "example",
        "target": "add",
        "test": "test_add",
        "file": expected_file,
        "line": expected_line,
    }


def test_extract_spec_from_tests_without_observations_exits_one_unpatched(
    tmp_path: Path,
    capsys,
) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_empty.py").write_text(
        "def test_only_literal():\n"
        "    assert 2 == 2\n",
        encoding="utf-8",
    )
    args = _args(
        tmp_path,
        "--from-tests",
        str(tests_dir),
        "--from-tests-language",
        "python",
    )

    with pytest.raises(SystemExit) as exc:
        main(args)

    assert exc.value.code == 1
    assert "Error: no test observations were harvested." in capsys.readouterr().err


@pytest.mark.parametrize(
    ("harvest_result", "error_message"),
    [
        ({**HARVEST, "observations": []}, "no test observations"),
        (HarvestInputError("bad test input"), "bad test input"),
    ],
)
def test_extract_spec_from_tests_rejects_empty_or_invalid_harvest(
    harvest_result,
    error_message: str,
    tmp_path: Path,
    capsys,
) -> None:
    args = _args(tmp_path, "--from-tests", str(tmp_path / "tests"))
    if isinstance(harvest_result, Exception):
        harvest_patch = patch(
            "agent.extract_spec.harvest_tests",
            side_effect=harvest_result,
        )
    else:
        harvest_patch = patch(
            "agent.extract_spec.harvest_tests",
            return_value=harvest_result,
        )
    with harvest_patch, pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 1
    assert error_message in capsys.readouterr().err


def test_extract_spec_from_tests_observation_error_exits_one(
    tmp_path: Path,
    capsys,
) -> None:
    args = _args(tmp_path, "--from-tests", str(tmp_path / "tests"))
    mumei = MagicMock()
    mumei.observe_check.return_value = {
        "returncode": 4,
        "report": None,
        "stderr": "observe unavailable",
    }
    with (
        patch("agent.extract_spec.AgentConfig", return_value=_config()),
        patch("agent.extract_spec.create_mumei_client", return_value=mumei),
        patch("agent.extract_spec.harvest_tests", return_value=HARVEST),
        patch(
            "agent.extract_spec.extract_spec",
            side_effect=lambda *pos, **kwargs: _call_checker_from_fake_extractor(
                SPEC, kwargs
            ),
        ),
    ):
        with pytest.raises(SystemExit) as exc:
            main(args)
    assert exc.value.code == 1
    assert "observe unavailable" in capsys.readouterr().err


def test_extract_spec_generate_rechecks_refined_spec_after_outputs(
    tmp_path: Path,
    capsys,
) -> None:
    output_path = tmp_path / "spec.json"
    generated_path = tmp_path / "generated.mm"
    observations_path = tmp_path / "report.json"
    args = build_parser().parse_args(
        [
            "--text",
            "Add two integers.",
            "--from-tests",
            str(tmp_path / "tests"),
            "--observations-output",
            str(observations_path),
            "--generate",
            "--generate-output",
            str(generated_path),
            "--output",
            str(output_path),
        ]
    )
    mumei = FakeMumei(["consistent", "contradicts_ensures"])
    with (
        patch("agent.extract_spec.AgentConfig", return_value=_config()),
        patch("agent.extract_spec.create_mumei_client", return_value=mumei),
        patch("agent.extract_spec.harvest_tests", return_value=HARVEST),
        patch(
            "agent.extract_spec.extract_spec",
            side_effect=lambda *pos, **kwargs: _call_checker_from_fake_extractor(
                SPEC, kwargs
            ),
        ),
        patch(
            "agent.strategies.spec_refinement.run_refinement_loop",
            return_value=("generated code", True, SPEC),
        ),
    ):
        with pytest.raises(SystemExit) as exc:
            main(args)

    assert exc.value.code == 1
    assert json.loads(output_path.read_text(encoding="utf-8")) == SPEC
    assert generated_path.read_text(encoding="utf-8") == "generated code"
    assert json.loads(observations_path.read_text(encoding="utf-8"))["results"][0][
        "verdict"
    ] == "contradicts_ensures"
    assert "ensures forbids it" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("verdict", "expected_exit"),
    [("consistent", 0), ("contradicts_ensures", 1)],
)
def test_extract_spec_generate_checks_normalized_single_atom(
    verdict: str,
    expected_exit: int,
    tmp_path: Path,
    capsys,
) -> None:
    single_atom_spec = {
        "name": "add",
        "params": [
            {"name": "a", "type": "i64"},
            {"name": "b", "type": "i64"},
        ],
        "return_type": "i64",
        "requires": "true",
        "ensures": "result == a + b",
    }
    output_path = tmp_path / "spec.json"
    generated_path = tmp_path / "generated.mm"
    args = build_parser().parse_args(
        [
            "--text",
            "Add two integers.",
            "--from-tests",
            str(tmp_path / "tests"),
            "--generate",
            "--generate-output",
            str(generated_path),
            "--output",
            str(output_path),
        ]
    )
    mumei = FakeMumei(["consistent", verdict])
    with (
        patch("agent.extract_spec.AgentConfig", return_value=_config()),
        patch("agent.extract_spec.create_mumei_client", return_value=mumei),
        patch("agent.extract_spec.harvest_tests", return_value=HARVEST),
        patch(
            "agent.extract_spec.extract_spec",
            side_effect=lambda *pos, **kwargs: _call_checker_from_fake_extractor(
                SPEC, kwargs
            ),
        ),
        patch(
            "agent.strategies.spec_refinement.run_refinement_loop",
            return_value=("generated code", True, single_atom_spec),
        ),
    ):
        try:
            main(args)
        except SystemExit as exc:
            assert exc.code == expected_exit
        else:
            assert expected_exit == 0

    assert len(mumei.calls) == 2
    assert "trusted atom add(a: i64, b: i64) -> i64" in mumei.calls[1][0]
    assert json.loads(output_path.read_text(encoding="utf-8")) == single_atom_spec
    assert generated_path.read_text(encoding="utf-8") == "generated code"
    stderr = capsys.readouterr().err
    assert ("ensures forbids it" in stderr) == (verdict == "contradicts_ensures")


@pytest.mark.parametrize(
    ("verified", "expected_exit"),
    [(True, 0), (False, 1)],
)
def test_extract_spec_generate_without_from_tests_matches_develop_output(
    verified: bool,
    expected_exit: int,
    tmp_path: Path,
    capsys,
) -> None:
    output_path = tmp_path / "spec.json"
    generated_path = tmp_path / "generated.mm"
    args = build_parser().parse_args(
        [
            "--text",
            "Add two integers.",
            "--generate",
            "--generate-output",
            str(generated_path),
            "--output",
            str(output_path),
        ]
    )
    with (
        patch("agent.extract_spec.AgentConfig", return_value=_config()),
        patch("agent.extract_spec.create_mumei_client", return_value=MagicMock()),
        patch("agent.extract_spec.extract_spec", return_value=SPEC),
        patch(
            "agent.strategies.spec_refinement.run_refinement_loop",
            return_value=("generated code", verified, SPEC),
        ),
    ):
        if expected_exit:
            with pytest.raises(SystemExit) as exc:
                main(args)
            assert exc.value.code == expected_exit
        else:
            main(args)

    captured = capsys.readouterr()
    expected_stdout = f"Extracted spec written to {output_path}\n"
    expected_stderr = "Extraction metrics: attempts=0, successes=0\n"
    if verified:
        expected_stdout += f"Generated verified code written to {generated_path}\n"
    else:
        expected_stderr += (
            f"Warning: Generated code written to {generated_path} "
            "but verification failed — output is NOT verified.\n"
        )
    assert captured.out == expected_stdout
    assert captured.err == expected_stderr
    assert generated_path.read_text(encoding="utf-8") == "generated code"


def test_extract_spec_without_from_tests_keeps_existing_output_bytes(
    tmp_path: Path,
    capsys,
) -> None:
    output_path = tmp_path / "spec.json"
    args = build_parser().parse_args(
        ["--text", "Add two integers.", "--output", str(output_path)]
    )
    with (
        patch("agent.extract_spec.AgentConfig", return_value=_config()),
        patch("agent.extract_spec.create_mumei_client", return_value=MagicMock()),
        patch("agent.extract_spec.extract_spec", return_value=SPEC),
    ):
        main(args)

    expected = json.dumps(SPEC, indent=2, ensure_ascii=False) + "\n"
    assert output_path.read_text(encoding="utf-8") == expected
    captured = capsys.readouterr()
    assert captured.out == f"Extracted spec written to {output_path}\n"
    assert captured.err == "Extraction metrics: attempts=0, successes=0\n"


def test_extract_spec_code_file_threads_observation_checker(
    tmp_path: Path,
    capsys,
) -> None:
    source = tmp_path / "lib.py"
    source.write_text("def add(a, b): return a + b\n", encoding="utf-8")
    args = build_parser().parse_args(
        [
            "--code-file",
            str(source),
            "--from-tests",
            str(tmp_path / "tests"),
            "--output",
            str(tmp_path / "spec.json"),
        ]
    )
    code_result = MagicMock(
        success=True,
        natural_language_spec="add returns the sum",
        forge_task_spec=SPEC,
        detected_language="python",
        warnings=[],
        errors=[],
    )
    fake_extractor = MagicMock()
    fake_extractor.extract_from_file.return_value = code_result
    mumei = FakeMumei()
    with (
        patch("agent.extract_spec.AgentConfig", return_value=_config()),
        patch("agent.extract_spec.create_mumei_client", return_value=mumei),
        patch("agent.extract_spec.harvest_tests", return_value=HARVEST),
        patch("agent.code_to_spec.CodeToSpecExtractor", return_value=fake_extractor),
    ):
        main(args)

    assert callable(fake_extractor.extract_from_file.call_args.kwargs["spec_checker"])
    assert "# Observed test behavior" in fake_extractor.extract_from_file.call_args.kwargs[
        "extra_context"
    ]
    assert len(mumei.calls) == 1
    assert "Code language: python" in capsys.readouterr().err


def test_extract_spec_rechecks_in_place_mutation_after_code_extraction(
    tmp_path: Path,
    capsys,
) -> None:
    source = tmp_path / "lib.py"
    source.write_text("def add(a, b): return a + b\n", encoding="utf-8")
    args = build_parser().parse_args(
        [
            "--code-file",
            str(source),
            "--from-tests",
            str(tmp_path / "tests"),
            "--output",
            str(tmp_path / "spec.json"),
        ]
    )
    mumei = FakeMumei(["consistent", "contradicts_ensures"])

    def extract_and_align(*_args, **kwargs):
        spec = copy.deepcopy(SPEC)
        kwargs["spec_checker"](spec)
        spec["atoms"][0]["ensures"] = "result == 0"
        return MagicMock(
            success=True,
            natural_language_spec="add returns the sum",
            forge_task_spec=spec,
            detected_language="python",
            warnings=[],
            errors=[],
        )

    fake_extractor = MagicMock()
    fake_extractor.extract_from_file.side_effect = extract_and_align
    with (
        patch("agent.extract_spec.AgentConfig", return_value=_config()),
        patch("agent.extract_spec.create_mumei_client", return_value=mumei),
        patch("agent.extract_spec.harvest_tests", return_value=HARVEST),
        patch("agent.code_to_spec.CodeToSpecExtractor", return_value=fake_extractor),
    ):
        with pytest.raises(SystemExit) as exc:
            main(args)

    assert exc.value.code == 1
    assert len(mumei.calls) == 2
    assert "ensures: result == a + b;" in mumei.calls[0][0]
    assert "ensures: result == 0;" in mumei.calls[1][0]
    assert json.loads((tmp_path / "spec.json").read_text(encoding="utf-8"))["atoms"][
        0
    ]["ensures"] == "result == 0"
    assert "ensures forbids it" in capsys.readouterr().err


def test_directory_merge_alone_receives_observation_checker(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "lib.py").write_text("def add(a, b): return a + b\n", encoding="utf-8")
    file_result = MagicMock(
        success=True,
        natural_language_spec="add returns the sum",
        forge_task_spec=SPEC,
        detected_language="python",
        warnings=[],
        errors=[],
    )
    checker = MagicMock()
    with (
        patch.object(
            CodeToSpecExtractor,
            "extract_from_file",
            return_value=file_result,
        ) as extract_file,
        patch("agent.extract_spec.extract_spec", return_value=SPEC) as merge,
    ):
        result = extract_spec_from_code_directory(
            _config(),
            source_dir,
            client=MagicMock(),
            spec_checker=checker,
            extra_context="# Observed test behavior",
        )

    assert result["merged_spec"] == SPEC
    assert "spec_checker" not in extract_file.call_args.kwargs
    assert "extra_context" not in extract_file.call_args.kwargs
    assert merge.call_args.kwargs["spec_checker"] is checker
    assert merge.call_args.kwargs["extra_context"] == "# Observed test behavior"
