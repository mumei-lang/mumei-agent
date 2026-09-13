"""Tests for budget-aware self-healing orchestration."""
from __future__ import annotations

import sys
from types import SimpleNamespace

from agent import self_healing


def test_first_allowed_attempt_reaches_get_fix(monkeypatch, tmp_path) -> None:
    source = tmp_path / "broken.mm"
    source.write_text("atom broken() -> i64 body: { 0 }\n", encoding="utf-8")
    policy = tmp_path / "budget.json"
    policy.write_text('{"max_attempts": 1}', encoding="utf-8")

    verify_calls = 0
    get_fix_calls = []
    history_lengths = []

    class FakeMumeiClient:
        def verify(self, _source_file: str) -> dict:
            nonlocal verify_calls
            verify_calls += 1
            if verify_calls == 1:
                return {
                    "success": False,
                    "stdout": "verification failed",
                    "stderr": "",
                    "report": {
                        "failure_type": "postcondition_violated",
                        "counterexample": {"x": 1},
                    },
                }
            return {"success": True, "stdout": "", "stderr": "", "report": {}}

    def fake_get_fix(*_args, **kwargs) -> str:
        get_fix_calls.append(kwargs["action_class"])
        history = kwargs["retry_history"]
        history_lengths.append(len(history.attempts))
        _args[4]["llm_tokens_used"] = 123
        return "atom fixed() -> i64 body: { 1 }\n"

    class FakePatternLibrary:
        def record(self, **_kwargs) -> None:
            pass

    monkeypatch.setattr(sys, "argv", [
        "agent",
        str(source),
        "--budget-policy",
        str(policy),
    ])
    monkeypatch.setattr(
        self_healing.AgentConfig,
        "create_client",
        lambda self: SimpleNamespace(),
    )
    monkeypatch.setattr(
        self_healing,
        "create_mumei_client",
        lambda _bin: FakeMumeiClient(),
    )
    monkeypatch.setattr(self_healing, "get_fix", fake_get_fix)
    monkeypatch.setattr(self_healing, "PatternLibrary", FakePatternLibrary)
    monkeypatch.setattr(self_healing.time, "sleep", lambda _seconds: None)

    self_healing.main()

    assert get_fix_calls == ["postcondition_fix"]
    assert history_lengths == [0]
    assert verify_calls == 2


def test_llm_token_usage_is_recorded_after_fix_selection(monkeypatch, tmp_path) -> None:
    source = tmp_path / "broken.mm"
    source.write_text("atom broken() -> i64 body: { 0 }\n", encoding="utf-8")
    policy = tmp_path / "budget.json"
    policy.write_text('{"max_attempts": 1, "max_tokens": 1000}', encoding="utf-8")

    recorded_tokens = []

    class FakeMumeiClient:
        def __init__(self) -> None:
            self.verify_calls = 0

        def verify(self, _source_file: str) -> dict:
            self.verify_calls += 1
            if self.verify_calls == 1:
                return {
                    "success": False,
                    "stdout": "verification failed",
                    "stderr": "",
                    "report": {
                        "failure_type": "postcondition_violated",
                        "counterexample": {"x": 1},
                    },
                }
            return {"success": True, "stdout": "", "stderr": "", "report": {}}

    def fake_get_fix(*_args, **_kwargs) -> str:
        _args[4]["llm_tokens_used"] = 456
        return "atom fixed() -> i64 body: { 1 }\n"

    def fake_aggregate_metrics(history):
        recorded_tokens.append(history.total_tokens())
        return SimpleNamespace(
            attempts_to_success=len(history.attempts),
            tokens_to_success=history.total_tokens(),
            solver_seconds_to_success=0.0,
            spec_drift_score=0.0,
        )

    class FakePatternLibrary:
        def record(self, **_kwargs) -> None:
            pass

    monkeypatch.setattr(sys, "argv", [
        "agent",
        str(source),
        "--budget-policy",
        str(policy),
    ])
    monkeypatch.setattr(
        self_healing.AgentConfig,
        "create_client",
        lambda self: SimpleNamespace(),
    )
    monkeypatch.setattr(
        self_healing,
        "create_mumei_client",
        lambda _bin: FakeMumeiClient(),
    )
    monkeypatch.setattr(self_healing, "get_fix", fake_get_fix)
    monkeypatch.setattr(self_healing, "aggregate_metrics", fake_aggregate_metrics)
    monkeypatch.setattr(self_healing, "PatternLibrary", FakePatternLibrary)
    monkeypatch.setattr(self_healing.time, "sleep", lambda _seconds: None)

    self_healing.main()

    assert recorded_tokens == [456]


def _capture_repair_certificate(monkeypatch):
    captured: list[dict] = []

    def fake_write(source_file, metadata, *, mumei_bin, out_path):
        captured.append(dict(metadata))
        return {"self_correction_summary": {}}

    monkeypatch.setattr(self_healing, "write_repair_certificate", fake_write)
    monkeypatch.setattr(self_healing.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        self_healing.AgentConfig, "create_client", lambda self: SimpleNamespace()
    )
    return captured


def _heal_with_cert(monkeypatch, source, cert_out, extra_argv=()):
    monkeypatch.setattr(
        sys, "argv", ["agent", str(source), "--proof-cert-out", str(cert_out), *extra_argv]
    )
    try:
        self_healing.main()
    except SystemExit as exc:
        return exc.code
    return 0


def test_repair_certificate_records_max_retries_exhausted(monkeypatch, tmp_path) -> None:
    source = tmp_path / "broken.mm"
    source.write_text("atom broken() -> i64 body: { 0 }\n", encoding="utf-8")

    class AlwaysFailing:
        def verify(self, _source_file: str) -> dict:
            return {
                "success": False,
                "stdout": "",
                "stderr": "",
                "report": {"failure_type": "postcondition_violated", "counterexample": {"x": 1}},
            }

    captured = _capture_repair_certificate(monkeypatch)
    monkeypatch.setattr(self_healing, "create_mumei_client", lambda _bin: AlwaysFailing())
    monkeypatch.setattr(
        self_healing, "get_fix", lambda *a, **k: "atom broken() -> i64 body: { 1 }\n"
    )

    code = _heal_with_cert(
        monkeypatch, source, tmp_path / "c.json", ["--max-retries", "1"]
    )
    assert code == 1
    assert captured[-1]["converged"] is False
    assert captured[-1]["final_error"] == "max_retries_exhausted"
    assert captured[-1]["repair_attempts"] == 1


def test_repair_certificate_records_exception_stop_reason(monkeypatch, tmp_path) -> None:
    source = tmp_path / "broken.mm"
    source.write_text("atom broken() -> i64 body: { 0 }\n", encoding="utf-8")

    class Crashing:
        def verify(self, _source_file: str) -> dict:
            raise RuntimeError("verifier unavailable")

    captured = _capture_repair_certificate(monkeypatch)
    monkeypatch.setattr(self_healing, "create_mumei_client", lambda _bin: Crashing())

    code = _heal_with_cert(monkeypatch, source, tmp_path / "c.json")
    assert code == 1
    assert captured[-1]["final_error"] == "exception:RuntimeError"
    assert captured[-1]["repair_attempts"] == 0


def test_directory_heal_forwards_per_file_proof_cert_out(monkeypatch, tmp_path) -> None:
    root = tmp_path / "src"
    (root / "sub").mkdir(parents=True)
    (root / "a.mm").write_text("atom a() -> i64 body: { 0 }\n", encoding="utf-8")
    (root / "sub" / "b.mm").write_text("atom b() -> i64 body: { 0 }\n", encoding="utf-8")
    seen: list[list[str]] = []

    def fake_main() -> None:
        seen.append(list(sys.argv))

    monkeypatch.setattr(self_healing, "main", fake_main)
    args = SimpleNamespace(
        max_retries=None, strategy=None, budget_policy=None, proof_cert_out=str(tmp_path / "certs")
    )
    payload = self_healing._run_directory_heal(root, args, "agent")
    assert payload["success"] is True
    forwarded = {argv[1]: argv[argv.index("--proof-cert-out") + 1] for argv in seen}
    assert forwarded == {
        str(root / "a.mm"): str(tmp_path / "certs" / "a.proof.json"),
        str(root / "sub" / "b.mm"): str(tmp_path / "certs" / "sub" / "b.proof.json"),
    }
