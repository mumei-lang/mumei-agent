from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent import self_correction
from agent.charter_guard import CharterGuard
from agent.erosion_guard import ErosionGuard
from agent.strategies import fix_strategy, self_correction_strategy
from agent.strategies.fix_strategy import SelfCorrectionLoop
from agent.strategies.self_correction_strategy import SelfCorrectionStrategy
from agent.self_correction import StructuredFeedbackSelfCorrectionLoop


def _erosion_fail() -> dict:
    return {
        "returncode": 1,
        "report": {
            "status": "fail",
            "atoms": [
                {
                    "name": "app",
                    "status": "post_weakened",
                    "detail": "bound dropped",
                    "counterexample": {"x": 4},
                }
            ],
        },
        "stderr": "",
    }


def _erosion_pass() -> dict:
    return {"returncode": 0, "report": {"status": "pass"}, "stderr": ""}


def _verified() -> dict:
    return {"success": True, "report": {}, "stdout": "", "stderr": ""}


class SequenceClient:
    def __init__(self, verifies: list[dict], erosions: list[dict]) -> None:
        self.verifies = list(verifies)
        self.erosions = list(erosions)
        self.erosion_calls = 0

    def verify(self, _source: str) -> dict:
        return self.verifies.pop(0)

    def erosion_check(self, _candidate: str, _baseline: str) -> dict:
        self.erosion_calls += 1
        return self.erosions.pop(0)


def test_structured_self_correction_retries_with_erosion_feedback(tmp_path: Path):
    source = tmp_path / "app.mm"
    source.write_text("original", encoding="utf-8")
    erosion_guard = ErosionGuard.create(source)
    try:
        client = SequenceClient([_verified(), _verified()], [_erosion_fail(), _erosion_pass()])
        reports: list[dict] = []

        def repair(*args: object) -> str:
            report = args[4]
            assert isinstance(report, dict)
            reports.append(report)
            return "repaired candidate"

        loop = StructuredFeedbackSelfCorrectionLoop(
            SimpleNamespace(),
            "model",
            client,
            convergence_threshold=1,
            repair_fn=repair,  # type: ignore[arg-type]
            max_retries=2,
            erosion_guard=erosion_guard,
        )
        result = loop.run(source, {"status": "verification_passed"})
        assert result.converged
        assert reports[0]["status"] == "erosion_failed"
        assert reports[0]["error_type"] == "contract_erosion"
        assert reports[0]["loss_vector"]["error_type"] == "contract_erosion"
        assert '"x": 4' in reports[0]["reason"]
        assert result.iterations[0].erosion_report["status"] == "fail"
    finally:
        erosion_guard.close()


def test_structured_final_erosion_failure_restores_original(tmp_path: Path, capsys):
    source = tmp_path / "app.mm"
    source.write_text("original", encoding="utf-8")
    original = source.read_bytes()
    erosion_guard = ErosionGuard.create(source)
    try:
        client = SequenceClient(
            [
                {
                    "success": False,
                    "report": {"failure_type": "postcondition_violated"},
                    "stdout": "",
                    "stderr": "verification failed",
                },
                _verified(),
            ],
            [_erosion_fail()],
        )
        loop = StructuredFeedbackSelfCorrectionLoop(
            SimpleNamespace(),
            "model",
            client,
            max_retries=1,
            convergence_threshold=1,
            repair_fn=lambda *_args: "weakened candidate",  # type: ignore[arg-type]
            erosion_guard=erosion_guard,
        )
        result = loop.run(source, {"status": "verification_failed"})
        assert not result.converged
        assert source.read_bytes() == original
        assert "Final candidate weakened its contract" in capsys.readouterr().out
    finally:
        erosion_guard.close()


def test_structured_loop_restores_after_identical_fix_exhausts_budget(tmp_path: Path):
    source = tmp_path / "app.mm"
    source.write_text("original", encoding="utf-8")
    original = source.read_bytes()
    erosion_guard = ErosionGuard.create(source)
    failure = {
        "success": False,
        "report": {
            "failure_type": "postcondition_violated",
            "structured_feedback": {
                "status": "verification_failed",
                "error_type": "postcondition_violated",
                "reconstruction_loss": {
                    "loss_set_size": 1,
                    "loss_vector": [{"violated_property": "p"}],
                },
            },
        },
        "stdout": "",
        "stderr": "verification failed",
    }
    client = SequenceClient(
        [failure, _verified(), _verified()],
        [_erosion_fail(), _erosion_fail()],
    )
    fixes: list[str] = []

    def same_fix(*_args: object) -> str:
        fixes.append("candidate")
        return "candidate"

    try:
        loop = StructuredFeedbackSelfCorrectionLoop(
            SimpleNamespace(),
            "model",
            client,
            max_retries=2,
            convergence_threshold=1,
            repair_fn=same_fix,  # type: ignore[arg-type]
            erosion_guard=erosion_guard,
        )
        result = loop.run(source, failure["report"]["structured_feedback"])
        assert not result.converged
        assert fixes == ["candidate", "candidate"]
        assert source.read_bytes() == original
    finally:
        erosion_guard.close()


def test_structured_verify_failure_keeps_candidate(tmp_path: Path):
    source = tmp_path / "app.mm"
    source.write_text("original", encoding="utf-8")
    erosion_guard = ErosionGuard.create(source)
    try:
        failure = {
            "success": False,
            "report": {
                "failure_type": "postcondition_violated",
                "structured_feedback": {
                    "status": "verification_failed",
                    "error_type": "postcondition_violated",
                    "reconstruction_loss": {
                        "loss_set_size": 1,
                        "loss_vector": [{"violated_property": "p"}],
                    },
                },
            },
            "stdout": "",
            "stderr": "verification failed",
        }
        client = SequenceClient([failure, failure], [])
        loop = StructuredFeedbackSelfCorrectionLoop(
            SimpleNamespace(),
            "model",
            client,
            max_retries=1,
            convergence_threshold=1,
            repair_fn=lambda *_args: "verification-failed candidate",  # type: ignore[arg-type]
            erosion_guard=erosion_guard,
        )
        loop.run(source, failure["report"]["structured_feedback"])
        assert source.read_text(encoding="utf-8") == "verification-failed candidate"
    finally:
        erosion_guard.close()


def test_charter_failure_takes_precedence_over_erosion(tmp_path: Path):
    source = tmp_path / "app.mm"
    source.write_text("original", encoding="utf-8")
    charter = tmp_path / "app.charter.mm"
    charter.write_text("pinned", encoding="utf-8")
    lock = tmp_path / "charter.lock"
    lock.write_text(
        json.dumps(
            {
                "schema": "mumei.charter-lock/v1",
                "charters": [{"path": charter.name}],
            }
        ),
        encoding="utf-8",
    )
    charter_guard = CharterGuard.discover(str(source), str(lock))
    assert charter_guard is not None
    erosion_guard = ErosionGuard.create(source)

    class BothGuardsClient(SequenceClient):
        def charter_check(self, *_args: object, **_kwargs: object) -> dict:
            return {
                "exit_code": 1,
                "report": {
                    "status": "fail",
                    "atoms": [{"name": "app", "status": "post_weakened"}],
                },
                "stdout": "",
                "stderr": "",
            }

    client = BothGuardsClient([_verified()], [])
    try:
        loop = StructuredFeedbackSelfCorrectionLoop(
            SimpleNamespace(),
            "model",
            client,
            max_retries=0,
            repair_fn=lambda *_args: "",
            guard=charter_guard,
            erosion_guard=erosion_guard,
        )
        result = loop.run(source, {"status": "verification_passed"})
        assert not result.converged
        assert client.erosion_calls == 0
    finally:
        erosion_guard.close()


def test_fix_strategy_loop_retries_erosion_and_exposes_feedback(tmp_path: Path):
    source = tmp_path / "app.mm"
    source.write_text("original", encoding="utf-8")
    erosion_guard = ErosionGuard.create(source)
    try:
        client = SequenceClient([_verified(), _verified()], [_erosion_fail(), _erosion_pass()])

        class FixClient:
            vectors: list[dict] = []

            def fix_with_loss_vector(self, _path: Path, vector: dict) -> str:
                self.vectors.append(vector)
                return "fixed candidate"

        llm = FixClient()
        result = SelfCorrectionLoop(max_iterations=2).run(
            source, client, llm, erosion_guard=erosion_guard
        )
        assert result.success
        assert llm.vectors[0]["error_type"] == "contract_erosion"
        assert '"x": 4' in llm.vectors[0]["feedback_instruction"]
        assert result.history[0]["erosion_report"]["status"] == "fail"
    finally:
        erosion_guard.close()


def test_fix_strategy_final_erosion_failure_restores_original(tmp_path: Path, capsys):
    source = tmp_path / "app.mm"
    source.write_text("original", encoding="utf-8")
    original = source.read_bytes()
    erosion_guard = ErosionGuard.create(source)
    try:
        client = SequenceClient([_verified()], [_erosion_fail()])

        class NoFix:
            def fix_with_loss_vector(self, _path: Path, _vector: dict) -> None:
                return None

        result = SelfCorrectionLoop(max_iterations=1).run(
            source, client, NoFix(), erosion_guard=erosion_guard
        )
        assert not result.success
        assert source.read_bytes() == original
        assert "Final candidate weakened its contract" in capsys.readouterr().out
    finally:
        erosion_guard.close()


def test_fix_strategy_restores_after_identical_fix_exhausts_budget(tmp_path: Path):
    source = tmp_path / "app.mm"
    source.write_text("original", encoding="utf-8")
    original = source.read_bytes()
    erosion_guard = ErosionGuard.create(source)
    failure = {
        "success": False,
        "loss_vector": {
            "status": "verification_failed",
            "error_type": "postcondition_violated",
            "feedback_instruction": "repair",
        },
        "report": {"failure_type": "postcondition_violated"},
    }
    client = SequenceClient([failure, _verified()], [_erosion_fail()])

    class SameFix:
        calls = 0

        def fix_with_loss_vector(self, _path: Path, _vector: dict) -> str:
            self.calls += 1
            return "eroded candidate"

    fixer = SameFix()
    try:
        result = SelfCorrectionLoop(max_iterations=2).run(
            source, client, fixer, erosion_guard=erosion_guard
        )
        assert not result.success
        assert fixer.calls == 2
        assert source.read_bytes() == original
    finally:
        erosion_guard.close()


def test_fix_strategy_verify_failure_does_not_restore_candidate(tmp_path: Path):
    source = tmp_path / "app.mm"
    source.write_text("original", encoding="utf-8")
    erosion_guard = ErosionGuard.create(source)
    try:
        failure = {
            "success": False,
            "loss_vector": {
                "status": "verification_failed",
                "error_type": "postcondition_violated",
                "feedback_instruction": "repair",
            },
            "report": {"failure_type": "postcondition_violated"},
        }
        client = SequenceClient([failure, failure], [])

        class FixClient:
            calls = 0

            def fix_with_loss_vector(self, _path: Path, _vector: dict) -> str | None:
                self.calls += 1
                return "verification-failed candidate" if self.calls == 1 else None

        SelfCorrectionLoop(max_iterations=2).run(
            source, client, FixClient(), erosion_guard=erosion_guard
        )
        assert source.read_text(encoding="utf-8") == "verification-failed candidate"
    finally:
        erosion_guard.close()


def test_standalone_strategy_retries_erosion_with_contract_feedback(
    monkeypatch, tmp_path: Path
):
    source = tmp_path / "app.mm"
    source.write_text("original", encoding="utf-8")
    erosion_guard = ErosionGuard.create(source)
    try:
        client = SequenceClient(
            [_verified(), _verified()], [_erosion_fail(), _erosion_pass()]
        )
        reports: list[dict] = []

        def fix(*args: object, **_kwargs: object) -> str:
            report = args[4]
            assert isinstance(report, dict)
            reports.append(report)
            return "fixed candidate"

        monkeypatch.setattr(
            self_correction_strategy.fix_strategy, "get_fix", fix
        )
        strategy = SelfCorrectionStrategy(
            SimpleNamespace(),
            "model",
            client,  # type: ignore[arg-type]
            max_repairs=1,
            required_successes=1,
            erosion_guard=erosion_guard,
        )
        result = strategy.run(source)
        assert result.converged
        assert reports[0]["failure_type"] == "contract_erosion"
        assert reports[0]["loss_vector"]["error_type"] == "contract_erosion"
        assert result.iterations[0].erosion_report["status"] == "fail"
    finally:
        erosion_guard.close()


def test_standalone_strategy_final_erosion_failure_restores_source(
    monkeypatch, tmp_path: Path, capsys
):
    source = tmp_path / "app.mm"
    source.write_text("original", encoding="utf-8")
    original = source.read_bytes()
    erosion_guard = ErosionGuard.create(source)
    try:
        client = SequenceClient(
            [
                {
                    "success": False,
                    "report": {"failure_type": "postcondition_violated"},
                    "stdout": "",
                    "stderr": "verification failed",
                },
                _verified(),
            ],
            [_erosion_fail()],
        )
        monkeypatch.setattr(
            self_correction_strategy.fix_strategy,
            "get_fix",
            lambda *_args, **_kwargs: "weakened candidate",
        )
        strategy = SelfCorrectionStrategy(
            SimpleNamespace(),
            "model",
            client,  # type: ignore[arg-type]
            max_repairs=1,
            required_successes=1,
            erosion_guard=erosion_guard,
        )
        result = strategy.run(source)
        assert not result.converged
        assert source.read_bytes() == original
        assert "Final candidate weakened its contract" in capsys.readouterr().out
    finally:
        erosion_guard.close()


def test_standalone_strategy_restores_after_identical_fix_exhausts_budget(
    monkeypatch, tmp_path: Path
):
    source = tmp_path / "app.mm"
    source.write_text("original", encoding="utf-8")
    original = source.read_bytes()
    erosion_guard = ErosionGuard.create(source)
    failure = {
        "success": False,
        "report": {"failure_type": "postcondition_violated"},
        "stdout": "",
        "stderr": "verification failed",
    }
    client = SequenceClient(
        [failure, _verified(), _verified()],
        [_erosion_fail(), _erosion_fail()],
    )
    fixes: list[str] = []

    def same_fix(*_args: object, **_kwargs: object) -> str:
        fixes.append("candidate")
        return "candidate"

    monkeypatch.setattr(self_correction_strategy.fix_strategy, "get_fix", same_fix)
    try:
        strategy = SelfCorrectionStrategy(
            SimpleNamespace(),
            "model",
            client,  # type: ignore[arg-type]
            max_repairs=2,
            required_successes=1,
            erosion_guard=erosion_guard,
        )
        result = strategy.run(source)
        assert not result.converged
        assert fixes == ["candidate", "candidate"]
        assert source.read_bytes() == original
    finally:
        erosion_guard.close()


@pytest.mark.parametrize("feedback_mode", [False, True])
def test_self_correct_cli_passes_erosion_guard_to_both_modes(
    feedback_mode: bool, monkeypatch, tmp_path: Path
):
    source = tmp_path / "app.mm"
    source.write_text("source", encoding="utf-8")
    captured: list[object] = []

    class Result:
        def to_dict(self) -> dict:
            return {"success": True}

    monkeypatch.setenv("ENABLE_CHARTER_GUARD", "false")
    monkeypatch.setenv("ENABLE_EROSION_GUARD", "true")
    monkeypatch.setattr(
        self_correction.AgentConfig, "create_client", lambda self: SimpleNamespace()
    )
    monkeypatch.setattr(self_correction, "create_mumei_client", lambda _bin: object())
    if feedback_mode:
        def fake_loop(**kwargs: object) -> Result:
            captured.append(kwargs["erosion_guard"])
            assert kwargs["erosion_guard"].baseline_path.read_text() == "source"
            return Result()

        monkeypatch.setattr(self_correction, "run_self_correction_loop", fake_loop)
        argv = [str(source), "--feedback", '{"status":"verification_passed"}']
    else:
        class FakeLoop:
            def __init__(self, **_kwargs: object) -> None:
                pass

            def run(self, *_args: object, erosion_guard=None, **_kwargs: object) -> Result:
                captured.append(erosion_guard)
                assert erosion_guard.baseline_path.read_text() == "source"
                return Result()

        monkeypatch.setattr(self_correction.fix_strategy, "SelfCorrectionLoop", FakeLoop)
        monkeypatch.setattr(
            self_correction.fix_strategy,
            "ConfiguredLossVectorFixClient",
            lambda *_args, **_kwargs: object(),
        )
        argv = [str(source)]
    args = self_correction.build_self_correct_parser().parse_args(argv)
    self_correction.main_self_correct(args)
    assert len(captured) == 1
    assert captured[0] is not None
    assert not captured[0].baseline_path.exists()


@pytest.mark.parametrize(
    ("extra_args", "enabled"),
    [(["--allow-contract-erosion"], True), ([], False)],
)
def test_self_correct_cli_can_disable_erosion_guard(
    monkeypatch, tmp_path: Path, extra_args: list[str], enabled: bool
):
    source = tmp_path / "app.mm"
    source.write_text("source", encoding="utf-8")
    captured: list[object] = []

    class Result:
        def to_dict(self) -> dict:
            return {}

    def fake_loop(**kwargs: object) -> Result:
        captured.append(kwargs["erosion_guard"])
        return Result()

    monkeypatch.setenv("ENABLE_CHARTER_GUARD", "false")
    monkeypatch.setenv("ENABLE_EROSION_GUARD", str(enabled).lower())
    monkeypatch.setattr(self_correction, "run_self_correction_loop", fake_loop)
    args = self_correction.build_self_correct_parser().parse_args(
        [str(source), "--feedback", '{"status":"verification_passed"}', *extra_args]
    )
    self_correction.main_self_correct(args)
    assert captured == [None]


@pytest.mark.parametrize(
    ("extra_args", "erosion_enabled"),
    [([], True), (["--allow-contract-erosion"], False)],
)
def test_standalone_strategy_cli_wires_erosion_guard(
    monkeypatch,
    tmp_path: Path,
    extra_args: list[str],
    erosion_enabled: bool,
):
    source = tmp_path / "app.mm"
    source.write_text("source", encoding="utf-8")
    captured: list[object] = []

    class Result:
        def to_dict(self) -> dict:
            return {"success": True}

    class FakeStrategy:
        def __init__(self, *_args: object, **kwargs: object) -> None:
            self.erosion_guard = kwargs.get("erosion_guard")

        def run(self, *_args: object, **_kwargs: object) -> Result:
            captured.append(self.erosion_guard)
            return Result()

    monkeypatch.setenv("ENABLE_CHARTER_GUARD", "false")
    monkeypatch.setenv("ENABLE_EROSION_GUARD", "true")
    monkeypatch.setattr(
        self_correction_strategy.AgentConfig,
        "create_client",
        lambda self: SimpleNamespace(),
    )
    monkeypatch.setattr(
        self_correction_strategy, "create_mumei_client", lambda _bin: object()
    )
    monkeypatch.setattr(
        self_correction_strategy, "SelfCorrectionStrategy", FakeStrategy
    )
    args = self_correction_strategy.build_parser().parse_args(
        [str(source), *extra_args]
    )
    self_correction_strategy.main(args)
    assert len(captured) == 1
    assert (captured[0] is not None) is erosion_enabled
    if captured[0] is not None:
        assert not captured[0].baseline_path.exists()


@pytest.mark.parametrize("pinned", [False, True])
def test_standalone_strategy_cli_rejects_invalid_or_pinned_charter(
    monkeypatch, tmp_path: Path, pinned: bool, capsys
):
    source = tmp_path / "app.mm"
    source.write_text("source", encoding="utf-8")
    lock = tmp_path / "charter.lock"
    if pinned:
        lock.write_text(
            '{"schema":"mumei.charter-lock/v1","charters":[{"path":"app.mm"}]}',
            encoding="utf-8",
        )
    else:
        lock.write_text("{", encoding="utf-8")
    monkeypatch.setenv("ENABLE_CHARTER_GUARD", "true")
    args = self_correction_strategy.build_parser().parse_args(
        [str(source), "--charter-lock", str(lock)]
    )
    with pytest.raises(SystemExit) as exc:
        self_correction_strategy.main(args)
    assert exc.value.code == 2
    message = capsys.readouterr().out
    assert (
        "refusing to heal a pinned charter file" in message
        if pinned
        else "could not parse charter lock" in message
    )
