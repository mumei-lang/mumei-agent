from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent import self_healing


def _source(tmp_path: Path) -> Path:
    source = tmp_path / "app.mm"
    source.write_text("atom app() -> i64 body: { 0 }\n", encoding="utf-8")
    return source


def _configure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    client: object,
    argv: list[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["mumei-heal", *argv])
    monkeypatch.setenv("ENABLE_CHARTER_GUARD", "false")
    monkeypatch.setenv("ENABLE_EROSION_GUARD", "false")
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


def _controls_result(status: str, survived: int = 0) -> dict:
    if status == "discriminating":
        tested, killed, unanalyzable = 2, 2, 0
        outcomes = [{"id": f"killed-{index}", "outcome": "killed"} for index in range(2)]
        returncode = 0
    elif status == "weak":
        tested, killed, unanalyzable = survived, 0, 0
        outcomes = [
            {"id": f"survived-{index}", "outcome": "survived"}
            for index in range(survived)
        ]
        returncode = 1
    elif status == "inconclusive":
        tested, killed, survived, unanalyzable = 1, 0, 0, 1
        outcomes = [{"id": "unknown", "outcome": "unanalyzable"}]
        returncode = 1
    else:
        raise ValueError(status)
    return {
        "returncode": returncode,
        "report": {
            "atoms": [
                {
                    "name": "app",
                    "status": status,
                    "tested": tested,
                    "killed": killed,
                    "survived": survived,
                    "unanalyzable": unanalyzable,
                    "mutants": outcomes,
                }
            ]
        },
        "stderr": "",
    }


def _unavailable_result() -> dict:
    return {
        "returncode": 2,
        "report": None,
        "stderr": "unrecognized subcommand 'controls'",
    }


class FakeClient:
    def __init__(
        self,
        controls: list[dict],
        erosions: list[dict] | None = None,
        *,
        charter_passes: bool = True,
    ) -> None:
        self.controls = iter(controls)
        self.erosions = iter(erosions or [])
        self.controls_calls = 0
        self.erosion_calls = 0
        self.charter_passes = charter_passes

    def verify(self, _source: str) -> dict:
        return {"success": True, "report": {}, "stdout": "", "stderr": ""}

    def controls_check(self, _source: str, *, atom: str) -> dict:
        assert atom == "app"
        self.controls_calls += 1
        return next(self.controls)

    def erosion_check(self, _source: str, _baseline: str) -> dict:
        self.erosion_calls += 1
        return next(self.erosions)

    def charter_check(
        self, _source: str, _lock: str, cwd: Path | None = None
    ) -> dict:
        return {
            "exit_code": 0 if self.charter_passes else 1,
            "report": {"status": "pass" if self.charter_passes else "fail", "atoms": []},
            "stdout": "",
            "stderr": "",
        }


def _ranking(capsys: pytest.CaptureFixture[str]) -> dict:
    output = capsys.readouterr().out
    line = next(
        line for line in output.splitlines()
        if line.startswith("Heal candidate ranking: ")
    )
    return json.loads(line.removeprefix("Heal candidate ranking: "))


def test_controls_gate_cli_default_is_off() -> None:
    args = self_healing._build_parser().parse_args(["app.mm"])
    assert args.controls_gate == "off"


def test_off_does_not_call_controls_or_change_success_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _source(tmp_path)
    client = FakeClient([])
    _configure(monkeypatch, tmp_path, client, [str(source), "--max-retries", "0"])
    monkeypatch.setenv("CONTROLS_GATE", "require")

    self_healing.main()

    output = capsys.readouterr().out
    assert client.controls_calls == 0
    assert "Success! Blade is flawless (Attempt 1)." in output
    assert "Heal candidate ranking:" not in output
    assert source.read_text(encoding="utf-8") == "atom app() -> i64 body: { 0 }\n"


def test_warn_accepts_clean_first_candidate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _source(tmp_path)
    client = FakeClient([_controls_result("discriminating")])
    _configure(
        monkeypatch,
        tmp_path,
        client,
        [str(source), "--max-retries", "0", "--controls-gate", "warn"],
    )

    self_healing.main()

    ranking = _ranking(capsys)
    assert client.controls_calls == 1
    assert ranking == {
        "mode": "warn",
        "candidates": [
            {
                "attempt": 1,
                "status": "clean",
                "weak_atoms": 0,
                "survived": 0,
                "selected": True,
            }
        ],
    }


def test_warn_continues_after_weak_feedback_until_clean_candidate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _source(tmp_path)
    client = FakeClient(
        [_controls_result("weak", 2), _controls_result("discriminating")]
    )
    reports: list[dict] = []

    def get_fix(*args: object, **_kwargs: object) -> str:
        reports.append(args[4])
        return "atom app() -> i64 body: { 1 }\n"

    _configure(
        monkeypatch,
        tmp_path,
        client,
        [str(source), "--max-retries", "1", "--controls-gate", "warn"],
    )
    monkeypatch.setattr(self_healing, "get_fix", get_fix)

    self_healing.main()

    ranking = _ranking(capsys)
    assert client.controls_calls == 2
    assert reports[0]["status"] == "controls_weak"
    assert reports[0]["failure_type"] == "weak_specification"
    assert reports[0]["controls"]["app"]["status"] == "weak"
    assert [entry["status"] for entry in ranking["candidates"]] == ["weak", "clean"]
    assert [entry["selected"] for entry in ranking["candidates"]] == [False, True]
    assert source.read_text(encoding="utf-8") == "atom app() -> i64 body: { 1 }\n"


def test_warn_fallback_selects_candidate_with_fewer_survivors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _source(tmp_path)
    client = FakeClient([_controls_result("weak", 3), _controls_result("weak", 1)])
    _configure(
        monkeypatch,
        tmp_path,
        client,
        [str(source), "--max-retries", "1", "--controls-gate", "warn"],
    )
    monkeypatch.setattr(
        self_healing,
        "get_fix",
        lambda *_args, **_kwargs: "atom app() -> i64 body: { 1 }\n",
    )

    self_healing.main()

    ranking = _ranking(capsys)
    assert source.read_text(encoding="utf-8") == "atom app() -> i64 body: { 1 }\n"
    assert [entry["survived"] for entry in ranking["candidates"]] == [3, 1]
    assert [entry["selected"] for entry in ranking["candidates"]] == [False, True]


def test_warn_fallback_breaks_ties_by_earlier_attempt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _source(tmp_path)
    original = source.read_text(encoding="utf-8")
    client = FakeClient([_controls_result("weak", 1), _controls_result("weak", 1)])
    _configure(
        monkeypatch,
        tmp_path,
        client,
        [str(source), "--max-retries", "1", "--controls-gate", "warn"],
    )
    monkeypatch.setattr(
        self_healing,
        "get_fix",
        lambda *_args, **_kwargs: "atom app() -> i64 body: { 1 }\n",
    )

    self_healing.main()

    ranking = _ranking(capsys)
    assert source.read_text(encoding="utf-8") == original
    assert [entry["selected"] for entry in ranking["candidates"]] == [True, False]


def test_warn_fallback_restores_weak_candidate_after_final_erosion_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _source(tmp_path)
    original = source.read_text(encoding="utf-8")
    client = FakeClient(
        [_controls_result("weak", 1)],
        [
            {"returncode": 0, "report": {"status": "pass"}, "stderr": ""},
            {
                "returncode": 1,
                "report": {
                    "status": "fail",
                    "atoms": [{"name": "app", "status": "post_weakened"}],
                },
                "stderr": "",
            },
        ],
    )
    _configure(
        monkeypatch,
        tmp_path,
        client,
        [str(source), "--max-retries", "1", "--controls-gate", "warn"],
    )
    monkeypatch.setenv("ENABLE_EROSION_GUARD", "true")
    monkeypatch.setattr(
        self_healing,
        "get_fix",
        lambda *_args, **_kwargs: "atom app() -> i64 body: { 1 }\n",
    )

    self_healing.main()

    ranking = _ranking(capsys)
    assert client.erosion_calls == 2
    assert client.controls_calls == 1
    assert source.read_text(encoding="utf-8") == original
    assert ranking["candidates"][0]["selected"] is True


def test_warn_fallback_applies_when_retry_budget_is_denied(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _source(tmp_path)
    client = FakeClient([_controls_result("weak", 1)])
    _configure(
        monkeypatch,
        tmp_path,
        client,
        [str(source), "--max-retries", "2", "--controls-gate", "warn"],
    )
    monkeypatch.setattr(
        self_healing,
        "evaluate_budget",
        lambda *_args, **_kwargs: SimpleNamespace(
            allowed=False,
            trigger_meta_architect=False,
            summary={"reason": "budget_denied"},
        ),
    )

    self_healing.main()

    ranking = _ranking(capsys)
    assert source.read_text(encoding="utf-8") == "atom app() -> i64 body: { 0 }\n"
    assert ranking["candidates"][0]["selected"] is True


def test_warn_fallback_applies_after_empty_fixes_exhaust_retries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _source(tmp_path)
    client = FakeClient([_controls_result("weak", 1), _controls_result("weak", 1)])
    _configure(
        monkeypatch,
        tmp_path,
        client,
        [str(source), "--max-retries", "1", "--controls-gate", "warn"],
    )
    monkeypatch.setattr(self_healing, "get_fix", lambda *_args, **_kwargs: "")

    self_healing.main()

    ranking = _ranking(capsys)
    assert source.read_text(encoding="utf-8") == "atom app() -> i64 body: { 0 }\n"
    assert [entry["selected"] for entry in ranking["candidates"]] == [True, False]


def test_warn_fallback_applies_to_manual_review_stop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _source(tmp_path)

    class Client(FakeClient):
        verify_calls = 0

        def verify(self, _source: str) -> dict:
            self.verify_calls += 1
            if self.verify_calls == 1:
                return super().verify(_source)
            return {
                "success": False,
                "report": {
                    "manual_review_required": {"reason": "needs a human"},
                },
                "stdout": "",
                "stderr": "",
            }

    client = Client([_controls_result("weak", 1)])
    fix_calls = 0

    def get_fix(*_args: object, **_kwargs: object) -> str:
        nonlocal fix_calls
        fix_calls += 1
        return (
            "atom app() -> i64 body: { 1 }\n"
            if fix_calls == 1
            else ""
        )

    _configure(
        monkeypatch,
        tmp_path,
        client,
        [str(source), "--max-retries", "2", "--controls-gate", "warn"],
    )
    monkeypatch.setattr(self_healing, "get_fix", get_fix)

    self_healing.main()

    ranking = _ranking(capsys)
    assert source.read_text(encoding="utf-8") == "atom app() -> i64 body: { 0 }\n"
    assert ranking["candidates"][0]["selected"] is True


def test_warn_does_not_fallback_after_exception(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _source(tmp_path)
    original = source.read_bytes()

    class Client(FakeClient):
        verify_calls = 0

        def verify(self, _source: str) -> dict:
            self.verify_calls += 1
            if self.verify_calls == 1:
                return super().verify(_source)
            raise RuntimeError("verification client failed")

    client = Client([_controls_result("weak", 1)])
    _configure(
        monkeypatch,
        tmp_path,
        client,
        [str(source), "--max-retries", "2", "--controls-gate", "warn"],
    )
    monkeypatch.setattr(
        self_healing,
        "get_fix",
        lambda *_args, **_kwargs: "atom app() -> i64 body: { 1 }\n",
    )

    with pytest.raises(SystemExit) as exc:
        self_healing.main()

    ranking = _ranking(capsys)
    assert exc.value.code == 1
    assert source.read_bytes() == original
    assert ranking["candidates"][0]["selected"] is False


def test_warn_does_not_fallback_after_charter_tampering(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _source(tmp_path)
    original = source.read_bytes()
    charter = tmp_path / "spec.charter.mm"
    charter.write_text("trusted atom app() -> i64 body: 0;\n", encoding="utf-8")
    lock = tmp_path / "charter.lock"
    lock.write_text(
        json.dumps(
            {
                "schema": "mumei.charter-lock/v1",
                "charters": [{"path": charter.name, "sha256": "ignored"}],
            }
        ),
        encoding="utf-8",
    )
    client = FakeClient([_controls_result("weak", 1)])

    def get_fix(*_args: object, **_kwargs: object) -> str:
        charter.write_text("tampered charter", encoding="utf-8")
        return "atom app() -> i64 body: { 1 }\n"

    _configure(
        monkeypatch,
        tmp_path,
        client,
        [
            str(source),
            "--max-retries",
            "2",
            "--controls-gate",
            "warn",
            "--charter-lock",
            str(lock),
        ],
    )
    monkeypatch.setenv("ENABLE_CHARTER_GUARD", "true")
    monkeypatch.setattr(self_healing, "get_fix", get_fix)

    with pytest.raises(SystemExit) as exc:
        self_healing.main()

    ranking = _ranking(capsys)
    assert exc.value.code == 1
    assert source.read_bytes() == original
    assert ranking["candidates"][0]["selected"] is False


def test_warn_treats_unavailable_controls_as_clean(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _source(tmp_path)
    client = FakeClient([_unavailable_result()])
    _configure(
        monkeypatch,
        tmp_path,
        client,
        [str(source), "--max-retries", "0", "--controls-gate", "warn"],
    )

    self_healing.main()

    ranking = _ranking(capsys)
    assert client.controls_calls == 1
    assert ranking["candidates"][0]["status"] == "clean"
    assert ranking["candidates"][0]["selected"] is True


def test_require_rejects_weak_candidate_and_restores_original(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _source(tmp_path)
    original = source.read_bytes()
    client = FakeClient([_controls_result("weak", 1)])
    _configure(
        monkeypatch,
        tmp_path,
        client,
        [str(source), "--max-retries", "0", "--controls-gate", "require"],
    )

    with pytest.raises(SystemExit) as exc:
        self_healing.main()

    ranking = _ranking(capsys)
    assert exc.value.code == 1
    assert source.read_bytes() == original
    assert ranking["candidates"][0]["selected"] is False


def test_require_rejects_unavailable_controls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _source(tmp_path)
    client = FakeClient([_unavailable_result()])
    _configure(
        monkeypatch,
        tmp_path,
        client,
        [str(source), "--max-retries", "0", "--controls-gate", "require"],
    )

    with pytest.raises(SystemExit) as exc:
        self_healing.main()

    ranking = _ranking(capsys)
    assert exc.value.code == 1
    assert ranking["candidates"][0]["status"] == "weak"
    assert ranking["candidates"][0]["selected"] is False


def test_malformed_controls_result_is_not_clean_in_warn_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _source(tmp_path)
    malformed = {
        "returncode": 1,
        "report": {"atoms": []},
        "stderr": "missing atom",
    }
    client = FakeClient([malformed, _controls_result("discriminating")])
    reports: list[dict] = []

    def get_fix(*args: object, **_kwargs: object) -> str:
        reports.append(args[4])
        return "atom app() -> i64 body: { 1 }\n"

    _configure(
        monkeypatch,
        tmp_path,
        client,
        [str(source), "--max-retries", "1", "--controls-gate", "warn"],
    )
    monkeypatch.setattr(self_healing, "get_fix", get_fix)

    self_healing.main()

    ranking = _ranking(capsys)
    assert reports[0]["status"] == "controls_weak"
    assert [entry["status"] for entry in ranking["candidates"]] == ["weak", "clean"]
    assert ranking["candidates"][1]["selected"] is True


def test_directory_heal_forwards_controls_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "app.mm"
    source.write_text("atom app() -> i64 body: { 0 }\n", encoding="utf-8")
    captured: list[list[str]] = []

    def fake_main() -> None:
        captured.append(sys.argv.copy())

    monkeypatch.setattr(self_healing, "main", fake_main)
    monkeypatch.setattr(self_healing, "build_dependency_graph", lambda _files: {})
    monkeypatch.setattr(self_healing, "topological_sort_files", lambda _graph: [source])
    args = SimpleNamespace(
        max_retries=None,
        strategy=None,
        budget_policy=None,
        charter_lock=None,
        proof_cert_out=None,
        allow_contract_erosion=False,
        controls_gate="require",
    )

    self_healing._run_directory_heal(tmp_path, args, "mumei-heal")

    assert captured[0][-2:] == ["--controls-gate", "require"]


def test_self_correction_warns_controls_ranking_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _source(tmp_path)
    client = FakeClient([])

    class SelfCorrectionResult:
        converged = True
        repair_attempts = 0
        token_cost = 0
        consecutive_successes = 0
        final_error = None

        def to_dict(self) -> dict:
            return {}

    _configure(
        monkeypatch,
        tmp_path,
        client,
        [str(source), "--max-retries", "0", "--controls-gate", "warn"],
    )
    monkeypatch.setenv("ENABLE_SELF_CORRECTION", "true")
    monkeypatch.setattr(
        "agent.self_correction.run_self_correction_loop",
        lambda *_args, **_kwargs: SelfCorrectionResult(),
    )

    self_healing.main()

    output = capsys.readouterr().out
    assert "--controls-gate ranking applies only to the classic heal loop" in output
    assert "ignored when self-correction is enabled" in output
    assert "Heal candidate ranking:" in output
    assert client.controls_calls == 0


def test_atom_names_include_trusted_atoms_and_skip_comment_lines() -> None:
    source = (
        "atom first() -> i64 body: { 0 }\n"
        "trusted atom trusted() -> i64 body: 0;\n"
        "// atom commented() -> i64 body: 0;\n"
    )
    assert self_healing._atom_names(source) == ["first", "trusted"]
