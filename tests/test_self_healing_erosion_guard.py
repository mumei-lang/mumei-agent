from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent import self_healing


def _configure(monkeypatch, tmp_path: Path, client: object, argv: list[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["mumei-heal", *argv])
    monkeypatch.setenv("ENABLE_CHARTER_GUARD", "false")
    monkeypatch.setenv("ENABLE_EROSION_GUARD", "true")
    monkeypatch.setenv("ENABLE_SELF_CORRECTION", "false")
    monkeypatch.delenv("CHARTER_LOCK_PATH", raising=False)
    monkeypatch.setattr(
        self_healing.AgentConfig, "create_client", lambda self: SimpleNamespace()
    )
    monkeypatch.setattr(self_healing, "create_mumei_client", lambda _bin: client)
    monkeypatch.setattr(self_healing.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(self_healing, "ROOT_DIR", tmp_path / "agent-root")

    class FakePatternLibrary:
        def record(self, **_kwargs: object) -> None:
            pass

    monkeypatch.setattr(self_healing, "PatternLibrary", FakePatternLibrary)


def _source(tmp_path: Path) -> Path:
    source = tmp_path / "app.mm"
    source.write_text("original source", encoding="utf-8")
    return source


def _erosion_failure() -> dict:
    return {
        "returncode": 1,
        "report": {
            "status": "fail",
            "atoms": [
                {
                    "name": "app",
                    "status": "post_weakened",
                    "detail": "upper bound dropped",
                    "counterexample": "x = 3",
                }
            ],
        },
        "stderr": "",
    }


def test_heal_retries_erosion_failure_and_accepts_later_candidate(
    monkeypatch, tmp_path: Path
) -> None:
    source = _source(tmp_path)
    reports: list[dict] = []

    class Client:
        verify_calls = 0
        erosion_calls = 0

        def verify(self, _source: str) -> dict:
            self.verify_calls += 1
            if self.verify_calls == 1:
                return {
                    "success": False,
                    "report": {"failure_type": "postcondition_violated"},
                    "stdout": "",
                    "stderr": "verification failed",
                }
            return {"success": True, "report": {}, "stdout": "", "stderr": ""}

        def erosion_check(self, _candidate: str, _baseline: str) -> dict:
            self.erosion_calls += 1
            return (
                _erosion_failure()
                if self.erosion_calls == 1
                else {"returncode": 0, "report": {"status": "pass"}, "stderr": ""}
            )

    client = Client()

    def fix(*args: object, **_kwargs: object) -> str:
        report = args[4]
        assert isinstance(report, dict)
        reports.append(report)
        return f"candidate {len(reports)}"

    _configure(monkeypatch, tmp_path, client, [str(source), "--max-retries", "2"])
    monkeypatch.setattr(self_healing, "get_fix", fix)
    self_healing.main()

    assert client.verify_calls == 3
    assert client.erosion_calls == 2
    assert reports[1]["status"] == "erosion_failed"
    assert reports[1]["failure_type"] == "contract_erosion"
    assert reports[1]["loss_vector"]["error_type"] == "contract_erosion"
    assert "x = 3" in reports[1]["reason"]
    assert source.read_text(encoding="utf-8") == "candidate 2"


def test_final_erosion_failure_restores_source(
    monkeypatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _source(tmp_path)
    original = source.read_bytes()

    class Client:
        verify_calls = 0

        def verify(self, _source: str) -> dict:
            self.verify_calls += 1
            if self.verify_calls == 1:
                return {
                    "success": False,
                    "report": {"failure_type": "postcondition_violated"},
                    "stdout": "",
                    "stderr": "verification failed",
                }
            return {"success": True, "report": {}, "stdout": "", "stderr": ""}

        def erosion_check(self, _candidate: str, _baseline: str) -> dict:
            return _erosion_failure()

    _configure(monkeypatch, tmp_path, Client(), [str(source), "--max-retries", "1"])
    monkeypatch.setattr(self_healing, "get_fix", lambda *_args, **_kwargs: "weakened")
    with pytest.raises(SystemExit) as exc:
        self_healing.main()
    assert exc.value.code == 1
    assert source.read_bytes() == original
    assert f"Final candidate weakened its contract; source restored from {source}" in (
        capsys.readouterr().out
    )


@pytest.mark.parametrize(
    ("extra_args", "env_value"),
    [
        (["--allow-contract-erosion"], None),
        ([], "false"),
    ],
)
def test_heal_can_disable_erosion_guard(
    monkeypatch, tmp_path: Path, extra_args: list[str], env_value: str | None
) -> None:
    source = _source(tmp_path)

    class Client:
        erosion_calls = 0

        def verify(self, _source: str) -> dict:
            return {"success": True, "report": {}, "stdout": "", "stderr": ""}

        def erosion_check(self, _candidate: str, _baseline: str) -> dict:
            self.erosion_calls += 1
            return _erosion_failure()

    client = Client()
    if env_value is not None:
        monkeypatch.setenv("ENABLE_EROSION_GUARD", env_value)
    _configure(
        monkeypatch,
        tmp_path,
        client,
        [str(source), "--max-retries", "0", *extra_args],
    )
    if env_value is not None:
        monkeypatch.setenv("ENABLE_EROSION_GUARD", env_value)
    self_healing.main()
    assert client.erosion_calls == 0


def test_old_mumei_skips_erosion_and_heal_succeeds(monkeypatch, tmp_path: Path):
    source = _source(tmp_path)

    class Client:
        def verify(self, _source: str) -> dict:
            return {"success": True, "report": {}, "stdout": "", "stderr": ""}

        def erosion_check(self, _candidate: str, _baseline: str) -> dict:
            return {
                "returncode": 2,
                "report": None,
                "stderr": "error: unrecognized subcommand 'erosion'",
            }

    _configure(monkeypatch, tmp_path, Client(), [str(source), "--max-retries", "0"])
    self_healing.main()
    assert source.read_text(encoding="utf-8") == "original source"


def test_generate_mode_does_not_create_or_run_erosion_guard(monkeypatch, tmp_path: Path):
    output = tmp_path / "generated.mm"
    spec = tmp_path / "spec.json"
    spec.write_text('{"name": "generated"}', encoding="utf-8")

    class Client:
        erosion_calls = 0

        def erosion_check(self, _candidate: str, _baseline: str) -> dict:
            self.erosion_calls += 1
            return _erosion_failure()

    client = Client()
    _configure(
        monkeypatch,
        tmp_path,
        client,
        ["--generate", str(spec), "--output", str(output)],
    )
    monkeypatch.setattr(
        self_healing, "generate_code", lambda *_args, **_kwargs: ("generated", True)
    )
    self_healing.main()
    assert client.erosion_calls == 0


def test_directory_heal_forwards_allow_contract_erosion(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "app.mm"
    source.write_text("source", encoding="utf-8")
    captured: list[list[str]] = []

    def fake_main() -> None:
        captured.append(sys.argv.copy())

    monkeypatch.setattr(self_healing, "main", fake_main)
    monkeypatch.setattr(self_healing, "build_dependency_graph", lambda _files: {})
    monkeypatch.setattr(self_healing, "topological_sort_files", lambda _graph: [source])
    args = SimpleNamespace(
        max_retries=1,
        strategy=None,
        budget_policy=None,
        charter_lock=None,
        proof_cert_out=None,
        allow_contract_erosion=True,
    )
    self_healing._run_directory_heal(tmp_path, args, "mumei-heal")
    assert "--allow-contract-erosion" in captured[0]
