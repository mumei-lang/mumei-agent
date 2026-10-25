from __future__ import annotations

import copy
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.extract_spec import build_parser, main
from agent.spec_extractor import extract_spec
from agent.test_observations import (
    align_harvest_to_spec,
    check_observations,
    observation_feedback_parts,
    spec_to_observe_module,
)


SPEC = {
    "task_id": "property-add",
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
REFINED_SPEC = {
    **SPEC,
    "atoms": [
        {
            **SPEC["atoms"][0],
            "ensures": "result == a + b && result >= a",
        }
    ],
}
PROPERTY = {
    "kind": "property",
    "target": "add",
    "args": {"a": {"var": "x"}, "b": 3},
    "test": "test_add_nonneg",
    "file": "test_add.py",
    "line": 8,
    "variables": [{"name": "x", "type": "i64", "min": 0, "max": 10}],
    "assumptions": ["x != 5"],
    "predicate": "result >= x",
}
HARVEST = {
    "schema": "mumei.test-harvest/v1",
    "targets": {"add": {"python": {"params": ["a", "b"]}}},
    "observations": [PROPERTY],
}


class PropertyMumei:
    def __init__(
        self,
        verdicts: list[str],
        detail: str | None = "x=0, result=-1",
    ):
        self.verdicts = list(verdicts)
        self.detail = detail
        self.calls: list[tuple[str, dict]] = []

    def observe_check(self, module_path: str, harvest_path: str):
        module = Path(module_path).read_text(encoding="utf-8")
        aligned = json.loads(Path(harvest_path).read_text(encoding="utf-8"))
        self.calls.append((module, aligned))
        verdict = self.verdicts.pop(0) if len(self.verdicts) > 1 else self.verdicts[0]
        result = {
            "kind": "property",
            "target": "add",
            "test": PROPERTY["test"],
            "file": PROPERTY["file"],
            "line": PROPERTY["line"],
            "args": aligned["observations"][0]["args"],
            "predicate": PROPERTY["predicate"],
            "verdict": verdict,
            "detail": self.detail,
        }
        return {
            "returncode": int(
                verdict in {"contradicts_ensures", "requires_admits_rejected"}
            ),
            "report": {
                "schema": "mumei.observation-check/v1",
                "results": [result],
            },
            "stderr": "",
        }


def _response(content: str):
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _llm_client(*specs: dict) -> MagicMock:
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _response(json.dumps(spec)) for spec in specs
    ]
    return client


def _config() -> MagicMock:
    config = MagicMock()
    config.model = "test-model"
    config.max_retries = 2
    config.mumei_bin = "mumei"
    config.create_client.return_value = MagicMock()
    return config


def _args(tmp_path: Path, *options: str):
    return build_parser().parse_args(
        [
            "--text",
            "Add two integers and return their sum.",
            *options,
            "--output",
            str(tmp_path / "spec.json"),
        ]
    )


def _report_row(verdict: str, detail: str | None = "x=0, result=-1") -> dict:
    return {
        "kind": "property",
        "target": "add",
        "test": PROPERTY["test"],
        "file": PROPERTY["file"],
        "line": PROPERTY["line"],
        "args": [{"var": "x"}, 3],
        "predicate": PROPERTY["predicate"],
        "verdict": verdict,
        "detail": detail,
    }


def test_property_feedback_retries_with_quantified_counterexample() -> None:
    mumei = PropertyMumei(["not_entailed", "entailed"])

    def checker(spec: dict):
        aligned = align_harvest_to_spec(HARVEST, spec)
        report = check_observations(spec_to_observe_module(spec), aligned, mumei)
        return observation_feedback_parts(report, spec, aligned)

    client = _llm_client(SPEC, SPEC)
    result = extract_spec(
        client,
        "test-model",
        "A function with properties",
        max_retries=2,
        spec_checker=checker,
        extra_context="for all x in [0, 10], assuming x != 5",
    )

    assert result == SPEC
    assert client.chat.completions.create.call_count == 2
    retry_prompt = client.chat.completions.create.call_args.kwargs["messages"][1][
        "content"
    ]
    assert "not guarantee it" in retry_prompt
    assert "for all x in [0, 10], assuming x != 5" in retry_prompt
    assert "(counterexample: x=0, result=-1)" in retry_prompt


def test_property_not_entailed_is_dropped_on_the_final_retry_attempt() -> None:
    mumei = PropertyMumei(["not_entailed"])

    def checker(spec: dict):
        aligned = align_harvest_to_spec(HARVEST, spec)
        report = check_observations(spec_to_observe_module(spec), aligned, mumei)
        return observation_feedback_parts(report, spec, aligned)

    client = _llm_client(SPEC)
    assert extract_spec(
        client,
        "test-model",
        "A function with properties",
        max_retries=1,
        spec_checker=checker,
    ) == SPEC
    assert client.chat.completions.create.call_count == 1


def test_property_contradiction_fails_extraction_after_each_attempt() -> None:
    mumei = PropertyMumei(["contradicts_ensures"])

    def checker(spec: dict):
        aligned = align_harvest_to_spec(HARVEST, spec)
        report = check_observations(spec_to_observe_module(spec), aligned, mumei)
        return observation_feedback_parts(report, spec, aligned)

    client = _llm_client(SPEC, SPEC)
    with pytest.raises(ValueError, match="contradict the predicate"):
        extract_spec(
            client,
            "test-model",
            "A function with properties",
            max_retries=2,
            spec_checker=checker,
        )
    assert client.chat.completions.create.call_count == 2


@pytest.mark.parametrize(
    ("verdict", "detail", "expect_warning", "expected_exit"),
    [
        ("not_entailed", "x=0, result=-1", True, 0),
        ("domain_exceeds_requires", None, True, 0),
        ("not_checked", "unsupported observation kind", True, 0),
        ("mystery_verdict", None, True, 0),
        ("contradicts_ensures", None, False, 1),
    ],
)
def test_extract_spec_cli_property_verdicts(
    verdict: str,
    detail: str | None,
    expect_warning: bool,
    expected_exit: int,
    tmp_path: Path,
    capsys,
) -> None:
    report_path = tmp_path / "observation-report.json"
    args = _args(
        tmp_path,
        "--from-tests",
        str(tmp_path / "tests"),
        "--observations-output",
        str(report_path),
    )
    mumei = PropertyMumei([verdict], detail=detail)

    def fake_extract(*_pos, **kwargs):
        kwargs["spec_checker"](SPEC)
        return SPEC

    with (
        patch("agent.extract_spec.AgentConfig", return_value=_config()),
        patch("agent.extract_spec.create_mumei_client", return_value=mumei),
        patch("agent.extract_spec.harvest_tests", return_value=HARVEST),
        patch("agent.extract_spec.extract_spec", side_effect=fake_extract),
    ):
        try:
            main(args)
        except SystemExit as exc:
            assert exc.code == expected_exit
        else:
            assert expected_exit == 0

    captured = capsys.readouterr()
    assert ("Warning:" in captured.err) is expect_warning
    if expected_exit:
        assert "Error:" in captured.err
    else:
        assert "Error:" not in captured.err
    if verdict == "not_entailed":
        assert "ensures do not guarantee" in captured.err
    if verdict == "not_checked":
        assert "does not support property observations" in captured.err
    if verdict == "mystery_verdict":
        assert "unrecognized=1" in captured.err
    written = json.loads(report_path.read_text(encoding="utf-8"))
    assert written["results"] == [_report_row(verdict, detail)]

    passed_harvest = mumei.calls[0][1]
    assert passed_harvest["observations"][0]["args"] == [{"var": "x"}, 3]
    assert passed_harvest["observations"][0]["variables"] == PROPERTY["variables"]
    assert passed_harvest["observations"][0]["assumptions"] == PROPERTY["assumptions"]
    assert passed_harvest["observations"][0]["predicate"] == PROPERTY["predicate"]


def test_generate_rechecks_refined_spec_with_property_rows(
    tmp_path: Path,
    capsys,
) -> None:
    generated = tmp_path / "generated.mm"
    args = _args(
        tmp_path,
        "--from-tests",
        str(tmp_path / "tests"),
        "--generate",
        "--generate-output",
        str(generated),
    )
    mumei = PropertyMumei(["entailed", "contradicts_ensures"])

    def fake_extract(*_pos, **kwargs):
        kwargs["spec_checker"](SPEC)
        return SPEC

    with (
        patch("agent.extract_spec.AgentConfig", return_value=_config()),
        patch("agent.extract_spec.create_mumei_client", return_value=mumei),
        patch("agent.extract_spec.harvest_tests", return_value=HARVEST),
        patch("agent.extract_spec.extract_spec", side_effect=fake_extract),
        patch(
            "agent.strategies.spec_refinement.run_refinement_loop",
            return_value=("generated", True, REFINED_SPEC),
        ),
    ):
        with pytest.raises(SystemExit) as exc:
            main(args)

    assert exc.value.code == 1
    assert len(mumei.calls) == 2
    assert "ensures: result == a + b;" in mumei.calls[0][0]
    assert "ensures: result == a + b && result >= a;" in mumei.calls[1][0]
    assert generated.read_text(encoding="utf-8") == "generated"
    assert "ensures contradict the predicate" in capsys.readouterr().err


def test_code_file_property_checker_still_bypasses_spec_cache(
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
    config = _config()
    config.spec_cache_dir = str(tmp_path / "warm-cache")
    extractor = MagicMock()
    extractor.extract_from_file.return_value = MagicMock(
        success=True,
        natural_language_spec="Add two integers.",
        forge_task_spec=SPEC,
        detected_language="python",
        warnings=[],
        errors=[],
    )
    mumei = PropertyMumei(["entailed"])
    with (
        patch("agent.extract_spec.AgentConfig", return_value=config),
        patch("agent.extract_spec.create_mumei_client", return_value=mumei),
        patch("agent.extract_spec.harvest_tests", return_value=HARVEST),
        patch("agent.code_to_spec.CodeToSpecExtractor", return_value=extractor),
    ):
        main(args)
    kwargs = extractor.extract_from_file.call_args.kwargs
    assert kwargs["spec_checker"] is not None
    assert len(mumei.calls) == 1
    assert "Observation checks:" in capsys.readouterr().err
