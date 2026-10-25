from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent import forge as forge_module
from agent import generate
from agent.config import AgentConfig
from agent.controls_gate import ControlsGate
from agent.forge import ForgeResult, MumeiForge
from agent.mumei_client import MumeiClient


def _atom_entry(
    name: str,
    status: str,
    *,
    tested: int = 1,
    killed: int = 0,
    survived: int = 0,
    unanalyzable: int = 0,
    surviving_ids: list[str] | None = None,
) -> dict:
    surviving_ids = surviving_ids or []
    mutants = [
        {"id": mutant_id, "outcome": "survived"}
        for mutant_id in surviving_ids
    ]
    mutants.extend(
        {"id": f"killed-{index}", "outcome": "killed"}
        for index in range(killed)
    )
    mutants.extend(
        {"id": f"unknown-{index}", "outcome": "unanalyzable"}
        for index in range(unanalyzable)
    )
    return {
        "name": name,
        "status": status,
        "tested": tested,
        "killed": killed,
        "survived": survived,
        "unanalyzable": unanalyzable,
        "mutants": mutants,
    }


def _client_result(name: str, status: str = "discriminating", **kwargs) -> dict:
    if status == "discriminating" and not any(
        key in kwargs for key in ("tested", "killed", "survived", "unanalyzable")
    ):
        kwargs.update(tested=1, killed=1)
    return {
        "returncode": 1 if status in {"weak", "inconclusive"} else 0,
        "report": {"atoms": [_atom_entry(name, status, **kwargs)]},
        "stderr": "",
    }


class TestControlsGate:
    def test_rc0_discriminating(self) -> None:
        client = MagicMock()
        client.controls_check.return_value = _client_result(
            "f", "discriminating", tested=2, killed=2
        )

        outcome = ControlsGate("require").check(client, "file.mm", ["f"])

        assert outcome.passed is True
        assert outcome.skipped is False
        assert outcome.atoms["f"]["status"] == "discriminating"
        assert outcome.atoms["f"]["killed"] == 2
        client.controls_check.assert_called_once_with("file.mm", atom="f")

    def test_rc1_weak_extracts_surviving_mutant_ids(self) -> None:
        client = MagicMock()
        client.controls_check.return_value = _client_result(
            "f",
            "weak",
            tested=2,
            survived=1,
            killed=1,
            surviving_ids=["constant:1->0@2"],
        )

        outcome = ControlsGate("require").check(client, "file.mm", ["f"])

        assert outcome.passed is False
        assert outcome.atoms["f"]["surviving"] == ["constant:1->0@2"]
        assert "f: constant:1->0@2" in outcome.summary

    def test_rc1_inconclusive_fails_require(self) -> None:
        client = MagicMock()
        client.controls_check.return_value = _client_result(
            "f", "inconclusive", tested=1, unanalyzable=1
        )

        outcome = ControlsGate("require").check(client, "file.mm", ["f"])

        assert outcome.passed is False
        assert outcome.atoms["f"]["status"] == "inconclusive"
        assert "f: inconclusive" in outcome.summary

    def test_unavailable_warns_once_and_is_non_blocking(self, capsys) -> None:
        client = MagicMock()
        client.controls_check.return_value = {
            "returncode": 2,
            "report": None,
            "stderr": "unrecognized subcommand 'controls'",
        }

        outcome = ControlsGate("warn").check(client, "file.mm", ["a", "b"])

        assert outcome.passed is True
        assert outcome.skipped is True
        assert client.controls_check.call_count == 2
        assert capsys.readouterr().err.count("WARNING:") == 1

    def test_unavailable_fails_require(self) -> None:
        client = MagicMock()
        client.controls_check.return_value = {
            "returncode": 2,
            "report": None,
            "stderr": "unrecognized subcommand controls",
        }

        outcome = ControlsGate("require").check(client, "file.mm", ["f"])

        assert outcome.passed is False
        assert outcome.skipped is True
        assert "f" in outcome.summary
        assert "unrecognized subcommand" in outcome.summary

    @pytest.mark.parametrize(
        "result",
        [
            {
                "returncode": 4,
                "report": {"atoms": []},
                "stderr": "bad input",
            },
            {"returncode": 0, "report": ["not", "an", "object"], "stderr": "bad json"},
            {
                "returncode": 1,
                "report": {"atoms": [_atom_entry("other", "weak")]},
                "stderr": "missing requested atom",
            },
        ],
        ids=["input-error", "non-dict-report", "missing-atom"],
    )
    def test_malformed_results_fail_closed(self, result: dict) -> None:
        client = MagicMock()
        client.controls_check.return_value = result

        outcome = ControlsGate("require").check(client, "file.mm", ["f"])

        assert outcome.passed is False
        assert "f" in outcome.summary
        assert result["stderr"] in outcome.summary

    def test_exception_fails_closed_and_names_atom(self) -> None:
        client = MagicMock()
        client.controls_check.side_effect = RuntimeError("process failed")

        outcome = ControlsGate("require").check(client, "file.mm", ["f"])

        assert outcome.passed is False
        assert "f" in outcome.summary
        assert "process failed" in outcome.summary
        assert "stderr:" in outcome.summary

    @pytest.mark.parametrize("status", ["no_mutants", "not_checked"])
    def test_no_mutants_and_not_checked_pass(self, status: str) -> None:
        client = MagicMock()
        client.controls_check.return_value = _client_result(
            "f", status, tested=0, killed=0, survived=0, unanalyzable=0
        )

        outcome = ControlsGate("require").check(client, "file.mm", ["f"])

        assert outcome.passed is True
        assert outcome.atoms["f"]["status"] == status

    def test_only_unique_task_atom_names_are_checked(self) -> None:
        client = MagicMock()
        client.controls_check.side_effect = [
            _client_result("Type::first"),
            _client_result("second"),
        ]

        outcome = ControlsGate("require").check(
            client, "file.mm", ["Type::first", "second", "Type::first"]
        )

        assert outcome.passed is True
        assert [call.kwargs["atom"] for call in client.controls_check.call_args_list] == [
            "Type::first",
            "second",
        ]


class TestMumeiClientControls:
    def test_controls_check_builds_json_command_and_parses_report(self) -> None:
        client = MumeiClient("mumei")
        report = {"atoms": []}
        completed = SimpleNamespace(returncode=0, stdout=json.dumps(report), stderr="")
        with patch.object(client, "_run_command", return_value=completed) as run:
            result = client.controls_check("contract.mm", atom="Type::method")

        command = run.call_args.args[0]
        assert command[-5:] == [
            "controls",
            "contract.mm",
            "--json",
            "--atom",
            "Type::method",
        ]
        assert result == {"returncode": 0, "report": report, "stderr": ""}


def _make_forge(tmp_path: Path, mode: str = "require") -> tuple[MumeiForge, MagicMock]:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    tasks = tmp_path / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    mumei = MagicMock()
    mumei.verify.return_value = {
        "success": True,
        "report": {},
        "stdout": "",
        "stderr": "",
    }
    mumei.controls_check.return_value = _client_result(
        "f",
        "discriminating",
        tested=1,
        killed=1,
    )
    forge = MumeiForge(
        config=SimpleNamespace(
            controls_gate=mode,
            model="test-model",
            mumei_bin="mumei",
            max_retries=1,
        ),
        mumei_client=mumei,
        mumei_repo_dir=repo,
        forge_tasks_dir=tasks,
        log_path=tmp_path / "forge_log.json",
        openai_client=MagicMock(),
    )
    return forge, mumei


def _deterministic_task(mode: str, name: str = "f") -> dict:
    return {
        "task_id": f"task-{mode}",
        "target_file": "std/generated.mm",
        "mode": mode,
        "deterministic_bodies": True,
        "atoms": [
            {
                "name": name,
                "inputs": [{"name": "x", "type": "i64"}],
                "requires": "x >= 0",
                "ensures": "result >= 0",
                "body": "x",
            }
        ],
    }


class TestForgeControlsGate:
    def test_warn_weak_succeeds_records_result_and_warns(self, tmp_path, capsys) -> None:
        forge, mumei = _make_forge(tmp_path, "warn")
        mumei.controls_check.return_value = _client_result(
            "f",
            "weak",
            tested=1,
            survived=1,
            surviving_ids=["constant:1->0@2"],
        )

        result = forge.forge_one(_deterministic_task("create"))

        assert result.status == "success"
        assert result.controls["mode"] == "warn"
        assert result.controls["atoms"]["f"]["surviving"] == ["constant:1->0@2"]
        assert "constant:1->0@2" in capsys.readouterr().err

    @pytest.mark.parametrize("mode", ["create", "replace", "append"])
    def test_require_weak_restores_target_and_does_not_commit(
        self, tmp_path, mode: str
    ) -> None:
        forge, mumei = _make_forge(tmp_path, "require")
        task = _deterministic_task(mode, name="added") if mode != "append" else {
            "task_id": "task-append",
            "target_file": "std/generated.mm",
            "mode": "append",
            "atoms": [{"name": "added"}],
            "auto_commit": True,
        }
        task["auto_commit"] = True
        target = forge.mumei_repo_dir / "std/generated.mm"
        original = b"existing atom old()\n"
        if mode in {"replace", "append"}:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(original)
        if mode == "append":
            def append_task(task, path, max_retries, *, metrics=None):
                path.write_bytes(original + b"\nnew atom\n")
                return "new atom", 1

            forge._forge_append = append_task
        mumei.controls_check.return_value = _client_result(
            "added",
            "weak",
            tested=1,
            survived=1,
            surviving_ids=["constant:1->0@2"],
        )
        forge._commit_change = MagicMock()
        forge.harness_metrics.record_result = MagicMock()

        result = forge.forge_one(task)

        assert result.status == "failed"
        assert result.error.startswith("weak specification: added:")
        assert result.controls["atoms"]["added"]["surviving"] == ["constant:1->0@2"]
        if mode == "create":
            assert not target.exists()
        else:
            assert target.read_bytes() == original
        assert [
            call.kwargs["atom"] for call in mumei.controls_check.call_args_list
        ] == ["added"]
        forge._commit_change.assert_not_called()
        assert any(
            call.args[0] == "forge_controls_gate"
            and call.kwargs["retry_class"] == "weak_spec"
            for call in forge.harness_metrics.record_result.call_args_list
        )

    def test_require_inconclusive_fails(self, tmp_path) -> None:
        forge, mumei = _make_forge(tmp_path, "require")
        mumei.controls_check.return_value = _client_result(
            "f", "inconclusive", tested=1, unanalyzable=1
        )

        result = forge.forge_one(_deterministic_task("create"))

        assert result.status == "failed"
        assert "f: inconclusive" in result.error

    @pytest.mark.parametrize("status", ["no_mutants", "not_checked"])
    def test_require_accepts_no_mutants_and_not_checked(
        self, tmp_path, status: str
    ) -> None:
        forge, mumei = _make_forge(tmp_path, "require")
        mumei.controls_check.return_value = _client_result(
            "f", status, tested=0, killed=0, survived=0, unanalyzable=0
        )

        result = forge.forge_one(_deterministic_task("create"))

        assert result.status == "success"

    def test_off_makes_no_controls_call_and_records_none(self, tmp_path) -> None:
        forge, mumei = _make_forge(tmp_path, "off")

        result = forge.forge_one(_deterministic_task("create"))

        assert result.status == "success"
        assert result.controls is None
        mumei.controls_check.assert_not_called()

    def test_deterministic_module_is_gated_and_only_task_atoms_checked(
        self, tmp_path
    ) -> None:
        forge, mumei = _make_forge(tmp_path, "require")
        task = _deterministic_task("create")
        task["atoms"].append(
            {
                "name": "Type::second",
                "inputs": [],
                "requires": "true",
                "ensures": "true",
                "body": "1",
            }
        )
        mumei.controls_check.side_effect = [
            _client_result("f", tested=1, killed=1),
            _client_result("Type::second", tested=1, killed=1),
        ]

        result = forge.forge_one(task)

        assert result.status == "success"
        assert [call.kwargs["atom"] for call in mumei.controls_check.call_args_list] == [
            "f",
            "Type::second",
        ]

    def test_post_write_verify_failure_never_calls_controls(self, tmp_path) -> None:
        forge, mumei = _make_forge(tmp_path, "require")
        mumei.verify.return_value = {
            "success": False,
            "report": {},
            "stdout": "",
            "stderr": "verification failed",
        }

        result = forge.forge_one(_deterministic_task("create"))

        assert result.status == "failed"
        mumei.controls_check.assert_not_called()

    def test_forge_result_and_log_include_controls(self, tmp_path) -> None:
        forge, _mumei = _make_forge(tmp_path, "warn")
        controls = {
            "mode": "warn",
            "skipped": False,
            "summary": "warning",
            "atoms": {"f": {"status": "weak", "surviving": ["m1"]}},
        }
        result = ForgeResult(
            task_id="logged",
            status="success",
            controls=controls,
        )
        assert result.to_dict()["controls"] == controls

        forge.log_result({"task_id": "logged"}, result)

        data = json.loads(forge.log_path.read_text(encoding="utf-8"))
        assert data["runs"][0]["controls"] == controls


class TestGenerateControlsGate:
    def _run(
        self,
        tmp_path: Path,
        monkeypatch,
        *,
        mode: str,
        verified: bool = True,
    ) -> tuple[Path, MagicMock, argparse.Namespace]:
        spec = {
            "name": "plus_one",
            "params": [{"name": "x", "type": "i64"}],
            "requires": "x >= 0",
            "ensures": "result >= 0",
        }
        output = tmp_path / "generated.mm"
        config = SimpleNamespace(
            controls_gate=mode,
            create_client=MagicMock(return_value=MagicMock()),
            mumei_bin="mumei",
            max_retries=1,
            model="test-model",
            prompt_report_truncate_chars=4000,
        )
        mumei = MagicMock()
        mumei.controls_check.return_value = _client_result(
            "plus_one",
            "weak",
            tested=1,
            survived=1,
            surviving_ids=["constant:1->0@2"],
        )
        monkeypatch.setattr(generate, "AgentConfig", lambda **_kwargs: config)
        monkeypatch.setattr(generate, "create_mumei_client", lambda _bin: mumei)
        monkeypatch.setattr(
            generate,
            "generate_code",
            lambda **_kwargs: ("atom plus_one(x: i64) body: x + 1;", verified),
        )
        args = generate.build_parser().parse_args(
            [
                "--spec",
                json.dumps(spec),
                "--output",
                str(output),
                "--controls-gate",
                mode,
            ]
        )
        return output, mumei, args

    def test_require_weak_exits_one_but_keeps_generated_file(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        output, mumei, args = self._run(
            tmp_path, monkeypatch, mode="require"
        )

        with pytest.raises(SystemExit) as exc:
            generate.main(args)

        assert exc.value.code == 1
        assert output.exists()
        assert "weak specification" in capsys.readouterr().err
        mumei.controls_check.assert_called_once_with(str(output), atom="plus_one")

    def test_warn_weak_exits_zero(self, tmp_path, monkeypatch, capsys) -> None:
        output, _mumei, args = self._run(tmp_path, monkeypatch, mode="warn")

        generate.main(args)

        assert output.exists()
        assert "constant:1->0@2" in capsys.readouterr().err

    def test_unverified_output_does_not_call_controls(
        self, tmp_path, monkeypatch
    ) -> None:
        output, mumei, args = self._run(
            tmp_path, monkeypatch, mode="require", verified=False
        )

        with pytest.raises(SystemExit) as exc:
            generate.main(args)

        assert exc.value.code == 1
        assert output.exists()
        mumei.controls_check.assert_not_called()

    def test_generate_cli_flag_overrides_environment(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.setenv("CONTROLS_GATE", "invalid")
        output = tmp_path / "generated.mm"
        spec = {
            "name": "plus_one",
            "params": [],
            "requires": "true",
            "ensures": "true",
        }
        created = {}

        def create_config(**kwargs):
            config = AgentConfig(**kwargs)
            config.create_client = MagicMock(return_value=MagicMock())
            created["config"] = config
            return config

        mumei = MagicMock()
        monkeypatch.setattr(generate, "AgentConfig", create_config)
        monkeypatch.setattr(generate, "create_mumei_client", lambda _bin: mumei)
        monkeypatch.setattr(
            generate,
            "generate_code",
            lambda **_kwargs: ("atom plus_one() body: 1;", True),
        )
        args = generate.build_parser().parse_args(
            [
                "--spec",
                json.dumps(spec),
                "--output",
                str(output),
                "--controls-gate",
                "off",
            ]
        )

        generate.main(args)

        assert created["config"].controls_gate == "off"
        mumei.controls_check.assert_not_called()


def test_forge_cli_flag_overrides_environment(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CONTROLS_GATE", "require")
    parser = argparse.ArgumentParser()
    forge_module.build_parser(parser)
    args = parser.parse_args(
        [
            "--tasks-dir",
            str(tmp_path),
            "--mumei-repo",
            str(tmp_path),
            "--controls-gate",
            "off",
        ]
    )
    captured = {}

    class StubForge:
        def __init__(self, *, config, **_kwargs):
            captured["config"] = config

        def run(self, **_kwargs):
            return []

    monkeypatch.setattr(forge_module, "MumeiForge", StubForge)
    monkeypatch.setattr(forge_module, "create_mumei_client", lambda _bin: MagicMock())

    forge_module.main(args)

    assert captured["config"].controls_gate == "off"


@pytest.mark.integration
def test_real_mumei_binary_controls_weak_and_strong_specs(tmp_path) -> None:
    binary = os.environ.get("MUMEI_BIN")
    if not binary:
        pytest.skip("MUMEI_BIN is not configured")
    client = MumeiClient(binary)

    def check(name: str, ensures: str) -> dict:
        path = tmp_path / f"{name}.mm"
        path.write_text(
            f"atom {name}(x: i64)\n"
            "    requires: x >= 0;\n"
            f"    ensures: {ensures};\n"
            "    body: x + 1;\n",
            encoding="utf-8",
        )
        result = client.controls_check(str(path), atom=name)
        if result["returncode"] == 2 and "unrecognized subcommand" in result["stderr"]:
            pytest.skip("configured MUMEI_BIN does not support controls")
        assert result["returncode"] in (0, 1), result["stderr"]
        return next(atom for atom in result["report"]["atoms"] if atom["name"] == name)

    weak = check("weak_contract", "result >= 0")
    strong = check("strong_contract", "result == x + 1")

    assert weak["status"] == "weak"
    assert any(
        mutant["id"].startswith("constant:1->0@")
        for mutant in weak["mutants"]
        if mutant["outcome"] == "survived"
    )
    assert strong["status"] == "discriminating"
