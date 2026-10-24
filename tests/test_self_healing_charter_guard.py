from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent import self_healing


def _make_project(root: Path) -> tuple[Path, Path, Path]:
    source = root / "app.mm"
    source.write_text("atom app() -> i64 body: { 0 }\n", encoding="utf-8")
    charter = root / "spec.charter.mm"
    charter.write_text("trusted atom app() -> i64 body: 0;\n", encoding="utf-8")
    lock = root / "charter.lock"
    lock.write_text(
        json.dumps(
            {
                "schema": "mumei.charter-lock/v1",
                "charters": [{"path": charter.name, "sha256": "ignored"}],
            }
        ),
        encoding="utf-8",
    )
    return source, charter, lock


def _configure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    client: object,
    argv: list[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["mumei-heal", *argv])
    monkeypatch.setenv("ENABLE_CHARTER_GUARD", "true")
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


def test_success_requires_charter_pass(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source, _charter, lock = _make_project(tmp_path)

    class Passing:
        def verify(self, _source: str) -> dict:
            return {"success": True, "report": {}, "stdout": "", "stderr": ""}

        def charter_check(
            self, _source: str, _lock: str, cwd: Path | None = None
        ) -> dict:
            return {
                "exit_code": 0,
                "report": {"status": "pass", "atoms": []},
                "stdout": "",
                "stderr": "",
            }

    client = Passing()
    _configure(monkeypatch, tmp_path, client, [str(source)])
    self_healing.main()


def test_charter_failure_is_sent_to_fixer_then_can_recover(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source, _charter, _lock = _make_project(tmp_path)
    captured_reports: list[dict] = []

    class Client:
        verify_calls = 0
        check_calls = 0

        def verify(self, _source: str) -> dict:
            self.verify_calls += 1
            return {"success": True, "report": {}, "stdout": "", "stderr": ""}

        def charter_check(
            self, _source: str, _lock: str, cwd: Path | None = None
        ) -> dict:
            self.check_calls += 1
            if self.check_calls == 1:
                return {
                    "exit_code": 1,
                    "report": {
                        "status": "fail",
                        "atoms": [
                            {"name": "app", "status": "post_weakened", "detail": "ensures"}
                        ],
                    },
                    "stdout": "",
                    "stderr": "",
                }
            return {
                "exit_code": 0,
                "report": {"status": "pass", "atoms": []},
                "stdout": "",
                "stderr": "",
            }

    client = Client()

    def fake_fix(*args: object, **_kwargs: object) -> str:
        report = args[4]
        assert isinstance(report, dict)
        captured_reports.append(report)
        return "atom app() -> i64 body: { 1 }\n"

    _configure(monkeypatch, tmp_path, client, [str(source), "--max-retries", "2"])
    monkeypatch.setattr(self_healing, "get_fix", fake_fix)
    self_healing.main()
    assert captured_reports[0]["status"] == "charter_failed"
    assert captured_reports[0]["failure_type"] == "charter_violation"
    assert captured_reports[0]["reason"] == "app: post_weakened (ensures)"
    assert client.verify_calls == 2
    assert client.check_calls == 2


def test_charter_tamper_restores_source_and_stops(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source, charter, lock = _make_project(tmp_path)
    original_source = source.read_bytes()
    original_charter = charter.read_bytes()
    captured_metadata: list[dict] = []

    class Client:
        def verify(self, _source: str) -> dict:
            return {"success": True, "report": {}, "stdout": "", "stderr": ""}

        def charter_check(
            self, _source: str, _lock: str, cwd: Path | None = None
        ) -> dict:
            return {
                "exit_code": 1,
                "report": {"status": "fail", "atoms": []},
                "stdout": "",
                "stderr": "",
            }

    def fake_fix(*_args: object, **_kwargs: object) -> str:
        charter.write_text("modified charter", encoding="utf-8")
        return "atom app() -> i64 body: { 1 }\n"

    def fake_certificate(_source: str, metadata: dict, **_kwargs: object) -> dict:
        captured_metadata.append(metadata)
        return {}

    _configure(
        monkeypatch,
        tmp_path,
        Client(),
        [str(source), "--proof-cert-out", str(tmp_path / "repair.json")],
    )
    monkeypatch.setattr(self_healing, "get_fix", fake_fix)
    monkeypatch.setattr(self_healing, "write_repair_certificate", fake_certificate)
    with pytest.raises(SystemExit) as exc:
        self_healing.main()
    assert exc.value.code == 1
    assert source.read_bytes() == original_source
    assert charter.read_bytes() != original_charter
    assert captured_metadata[-1]["final_error"] == "charter_tampered"
    assert lock.exists()


def test_refuses_to_heal_a_pinned_charter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _source, charter, lock = _make_project(tmp_path)
    _configure(monkeypatch, tmp_path, object(), [str(charter), "--charter-lock", str(lock)])
    with pytest.raises(SystemExit) as exc:
        self_healing.main()
    assert exc.value.code == 2
    assert "refusing to heal a pinned charter file" in capsys.readouterr().out


def test_no_lock_does_not_call_charter_check(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("CHARTER_LOCK_PATH", raising=False)
    source = tmp_path / "app.mm"
    source.write_text("atom app() -> i64 body: { 0 }\n", encoding="utf-8")

    class Passing:
        def verify(self, _source: str) -> dict:
            return {"success": True, "report": {}, "stdout": "", "stderr": ""}

    _configure(monkeypatch, tmp_path, Passing(), [str(source)])
    self_healing.main()
