from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.observe_tests import build_parser, main
from agent.test_harvest import HarvestInputError


SPEC = {
    "atoms": [
        {
            "name": "f",
            "inputs": [{"name": "x", "type": "i64"}],
            "return_type": "i64",
            "requires": "true",
            "ensures": "result == x",
        }
    ]
}
HARVEST = {
    "schema": "mumei.test-harvest/v1",
    "targets": {"f": {"python": {"params": ["x"]}}},
    "observations": [
        {
            "kind": "example",
            "target": "f",
            "args": {"x": 2},
            "result": 2,
            "test": "test_f",
            "file": "test_f.py",
            "line": 2,
        }
    ],
    "totals": {"tests": 1},
}


def _report(verdict: str) -> dict:
    return {
        "schema": "mumei.observation-check/v1",
        "file": "contract.mm",
        "harvest": "harvest.json",
        "results": [
            {
                "kind": "example",
                "target": "f",
                "test": "test_f",
                "file": "test_f.py",
                "line": 2,
                "args": [2],
                "result": 2,
                "verdict": verdict,
                "detail": "test detail",
            }
        ],
        "totals": {
            "consistent": int(verdict == "consistent"),
            "contradicts_ensures": int(verdict == "contradicts_ensures"),
        },
    }


def _cli_args(tmp_path: Path, mode: str, *extra: str):
    source = tmp_path / "f.py"
    source.write_text("def f(x): return x\n", encoding="utf-8")
    source_args = (
        ["--mm", str(tmp_path / "contract.mm")]
        if mode == "mm"
        else ["--spec", str(tmp_path / "spec.json")]
    )
    if mode == "spec":
        (tmp_path / "spec.json").write_text(json.dumps(SPEC), encoding="utf-8")
    return build_parser().parse_args(
        [*source_args, str(source), *extra]
    )


@pytest.mark.parametrize(
    ("mode", "verdict", "expected"),
    [
        ("mm", "consistent", 0),
        ("spec", "consistent", 0),
        ("mm", "contradicts_ensures", 1),
        ("spec", "contradicts_ensures", 1),
        ("spec", "requires_admits_rejected", 1),
    ],
)
def test_observe_tests_cli_returns_zero_or_one_for_both_contract_sources(
    mode: str,
    verdict: str,
    expected: int,
    tmp_path: Path,
    capsys,
) -> None:
    client = MagicMock()
    client.observe_check.return_value = {
        "returncode": int(
            verdict in {"contradicts_ensures", "requires_admits_rejected"}
        ),
        "report": _report(verdict),
        "stderr": "",
    }
    args = _cli_args(tmp_path, mode)
    with (
        patch("agent.observe_tests.harvest_tests", return_value=HARVEST) as harvest,
        patch("agent.observe_tests.create_mumei_client", return_value=client),
    ):
        result = main(args)

    assert result == expected
    harvest.assert_called_once()
    client.observe_check.assert_called_once()
    captured = capsys.readouterr()
    assert "Observation checks:" in captured.err
    assert json.loads(captured.out)["results"][0]["verdict"] == verdict


@pytest.mark.parametrize(
    ("mode", "verdict", "expected"),
    [
        ("spec", "not_entailed", 0),
        ("spec", "contradicts_ensures", 1),
        ("mm", "not_entailed", 0),
    ],
)
def test_observe_tests_cli_property_warnings_and_blocking(
    mode: str,
    verdict: str,
    expected: int,
    tmp_path: Path,
    capsys,
) -> None:
    property_harvest = {
        "schema": "mumei.test-harvest/v1",
        "targets": {"f": {"python": {"params": ["x"]}}},
        "observations": [
            {
                "kind": "property",
                "target": "f",
                "args": [{"var": "x"}],
                "test": "test_f_property",
                "file": "test_f.py",
                "line": 7,
                "variables": [{"name": "x", "type": "i64", "min": 0}],
                "assumptions": ["x != 5"],
                "predicate": "result >= x",
            }
        ],
    }
    report = {
        "schema": "mumei.observation-check/v1",
        "results": [
            {
                "kind": "property",
                "target": "f",
                "args": [{"var": "x"}],
                "test": "test_f_property",
                "file": "test_f.py",
                "line": 7,
                "predicate": "result >= x",
                "verdict": verdict,
                "detail": "x=0, result=-1",
            }
        ],
    }
    client = MagicMock()
    client.observe_check.return_value = {
        "returncode": int(verdict == "contradicts_ensures"),
        "report": report,
        "stderr": "",
    }
    args = _cli_args(tmp_path, mode)
    with (
        patch(
            "agent.observe_tests.harvest_tests",
            return_value=property_harvest,
        ),
        patch("agent.observe_tests.create_mumei_client", return_value=client),
    ):
        result = main(args)

    assert result == expected
    captured = capsys.readouterr()
    if verdict == "not_entailed":
        assert "Warning: test test_f_property" in captured.err
        assert "(counterexample: x=0, result=-1)" in captured.err
    else:
        assert "Warning:" not in captured.err
    assert json.loads(captured.out)["results"] == report["results"]


@pytest.mark.parametrize(
    ("mode", "expected_args"),
    [("mm", {"x": 2}), ("spec", [2])],
)
def test_observe_tests_aligns_only_spec_mode(
    mode: str,
    expected_args,
    tmp_path: Path,
) -> None:
    args = _cli_args(tmp_path, mode)
    captured: dict = {}

    def observe_check(_module: str, harvest_path: str):
        captured.update(json.loads(Path(harvest_path).read_text(encoding="utf-8")))
        return {
            "returncode": 0,
            "report": _report("consistent"),
            "stderr": "",
        }

    client = MagicMock()
    client.observe_check.side_effect = observe_check
    with (
        patch("agent.observe_tests.harvest_tests", return_value=HARVEST),
        patch("agent.observe_tests.create_mumei_client", return_value=client),
    ):
        assert main(args) == 0

    assert captured["observations"][0]["args"] == expected_args


@pytest.mark.parametrize("mode", ["mm", "spec"])
def test_observe_tests_cli_maps_observation_check_errors_to_four(
    mode: str,
    tmp_path: Path,
    capsys,
) -> None:
    client = MagicMock()
    client.observe_check.return_value = {
        "returncode": 4,
        "report": None,
        "stderr": "invalid input",
    }
    args = _cli_args(tmp_path, mode)
    with (
        patch("agent.observe_tests.harvest_tests", return_value=HARVEST),
        patch("agent.observe_tests.create_mumei_client", return_value=client),
    ):
        assert main(args) == 4
    assert "invalid input" in capsys.readouterr().err


def test_observe_tests_cli_maps_harvest_errors_and_empty_observations_to_four(
    tmp_path: Path,
    capsys,
) -> None:
    args = _cli_args(tmp_path, "mm")
    with patch(
        "agent.observe_tests.harvest_tests",
        side_effect=HarvestInputError("bad source"),
    ):
        assert main(args) == 4
    assert "bad source" in capsys.readouterr().err

    with patch(
        "agent.observe_tests.harvest_tests",
        return_value={**HARVEST, "observations": []},
    ):
        assert main(args) == 4
    assert "no test observations" in capsys.readouterr().err


def test_observe_tests_cli_writes_report_and_filters_targets(
    tmp_path: Path,
    capsys,
) -> None:
    output = tmp_path / "report.json"
    args = _cli_args(tmp_path, "mm", "--target", "f", "--output", str(output))
    client = MagicMock()
    client.observe_check.return_value = {
        "returncode": 0,
        "report": _report("consistent"),
        "stderr": "",
    }
    with (
        patch("agent.observe_tests.harvest_tests", return_value=HARVEST) as harvest,
        patch("agent.observe_tests.create_mumei_client", return_value=client),
    ):
        assert main(args) == 0
    assert harvest.call_args.args[2] == {"f"}
    assert json.loads(output.read_text(encoding="utf-8"))["schema"] == (
        "mumei.observation-check/v1"
    )
    assert capsys.readouterr().out == ""


def test_observe_tests_cli_rejects_invalid_spec_json(tmp_path: Path, capsys) -> None:
    args = _cli_args(tmp_path, "spec")
    Path(args.spec).write_text("{", encoding="utf-8")
    with patch("agent.observe_tests.harvest_tests", return_value=HARVEST):
        assert main(args) == 4
    assert "Expecting property name" in capsys.readouterr().err


def test_observe_tests_real_mumei_integration(tmp_path: Path, monkeypatch, capsys) -> None:
    binary = os.environ.get("MUMEI_BIN")
    if not binary:
        pytest.skip("MUMEI_BIN is not set")
    probe = subprocess.run(
        [binary, "observe", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        pytest.skip("MUMEI_BIN does not support observe")

    (tmp_path / "lib.py").write_text(
        "def add(a, b): return a + b\n"
        "def sub(x): return x - 1\n",
        encoding="utf-8",
    )
    (tmp_path / "test_lib.py").write_text(
        "from lib import add, sub\n"
        "def test_add(): assert add(2, 3) == 5\n"
        "def test_sub(): assert sub(2) == 1\n",
        encoding="utf-8",
    )
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(
        json.dumps(
            {
                "atoms": [
                    {
                        "name": "add",
                        "inputs": [
                            {"name": "a", "type": "i64"},
                            {"name": "b", "type": "i64"},
                        ],
                        "return_type": "i64",
                        "requires": "true",
                        "ensures": "result == a + b",
                    },
                    {
                        "name": "sub",
                        "inputs": [{"name": "x", "type": "i64"}],
                        "return_type": "i64",
                        "requires": "true",
                        "ensures": "result == x + 1",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MUMEI_BIN", binary)
    args = build_parser().parse_args(
        ["--spec", str(spec_path), str(tmp_path), "--language", "python"]
    )

    assert main(args) == 1
    report = json.loads(capsys.readouterr().out)
    verdicts = {item["target"]: item["verdict"] for item in report["results"]}
    assert verdicts == {"add": "consistent", "sub": "contradicts_ensures"}
