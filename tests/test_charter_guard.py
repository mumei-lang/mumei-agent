from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.charter_guard import CharterGuard
from agent.config import AgentConfig


def _make_lock(root: Path, charter_path: str = "spec.charter.mm") -> Path:
    (root / charter_path).parent.mkdir(parents=True, exist_ok=True)
    (root / charter_path).write_text("trusted atom f() -> i64 body: 0;\n", encoding="utf-8")
    lock_path = root / "charter.lock"
    lock_path.write_text(
        json.dumps(
            {
                "schema": "mumei.charter-lock/v1",
                "charters": [{"path": charter_path, "sha256": "ignored"}],
            }
        ),
        encoding="utf-8",
    )
    return lock_path


def test_discover_returns_none_without_lock(tmp_path: Path) -> None:
    source = tmp_path / "src" / "app.mm"
    source.parent.mkdir()
    source.write_text("atom f() -> i64 body: { 0 }\n", encoding="utf-8")
    assert CharterGuard.discover(str(source)) is None


def test_discover_finds_adjacent_lock(tmp_path: Path) -> None:
    source = tmp_path / "app.mm"
    source.write_text("implementation", encoding="utf-8")
    lock = _make_lock(tmp_path)
    guard = CharterGuard.discover(str(source))
    assert guard is not None
    assert guard.lock_path == lock.resolve()
    assert guard.root == tmp_path.resolve()


def test_discover_uses_manifest_lock_path(tmp_path: Path) -> None:
    source = tmp_path / "src" / "app.mm"
    source.parent.mkdir()
    source.write_text("implementation", encoding="utf-8")
    (tmp_path / "mumei.toml").write_text(
        '[charter]\nlock = "locks/charter.lock"\n', encoding="utf-8"
    )
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir()
    charter = tmp_path / "specs" / "core.charter.mm"
    charter.parent.mkdir()
    charter.write_text("trusted atom f() -> i64 body: 0;\n", encoding="utf-8")
    selected_lock = lock_dir / "charter.lock"
    selected_lock.write_text(
        json.dumps(
            {
                "schema": "mumei.charter-lock/v1",
                "charters": [{"path": "specs/core.charter.mm", "sha256": "ignored"}],
            }
        ),
        encoding="utf-8",
    )
    guard = CharterGuard.discover(str(source))
    assert guard is not None
    assert guard.lock_path == selected_lock.resolve()
    assert guard.root == tmp_path.resolve()
    assert str(charter.resolve()) in guard.snapshot

    class FakeClient:
        def charter_check(
            self,
            source_path: str,
            lock_path: str,
            cwd: Path | None = None,
        ) -> dict:
            assert cwd == tmp_path.resolve()
            return {
                "exit_code": 0,
                "report": {"status": "pass"},
                "stdout": "",
                "stderr": "",
            }

    assert guard.check(FakeClient(), str(source)).passed
    charter.write_text("changed charter", encoding="utf-8")
    assert guard.tampered() == [str(charter.resolve())]


def test_explicit_lock_uses_manifest_root(tmp_path: Path) -> None:
    project = tmp_path / "project"
    source = project / "src" / "app.mm"
    source.parent.mkdir(parents=True)
    source.write_text("implementation", encoding="utf-8")
    (project / "mumei.toml").write_text("[charter]\n", encoding="utf-8")
    lock_dir = project / "locks"
    lock_dir.mkdir()
    charter = project / "specs" / "core.charter.mm"
    charter.parent.mkdir()
    charter.write_text("pinned", encoding="utf-8")
    lock = lock_dir / "custom.lock"
    lock.write_text(
        json.dumps(
            {
                "schema": "mumei.charter-lock/v1",
                "charters": [{"path": "specs/core.charter.mm", "sha256": "ignored"}],
            }
        ),
        encoding="utf-8",
    )

    guard = CharterGuard.discover(str(source), str(lock))
    assert guard is not None
    assert guard.root == project.resolve()
    assert str(charter.resolve()) in guard.snapshot


def test_explicit_lock_without_manifest_uses_lock_parent(tmp_path: Path) -> None:
    project = tmp_path / "project"
    lock_dir = project / "locks"
    lock = _make_lock(lock_dir)
    source = project / "src" / "app.mm"
    source.parent.mkdir(parents=True)
    source.write_text("implementation", encoding="utf-8")

    guard = CharterGuard.discover(str(source), str(lock))
    assert guard is not None
    assert guard.root == lock_dir.resolve()


def test_discover_stops_at_manifest(tmp_path: Path) -> None:
    project = tmp_path / "project"
    nested = project / "src"
    nested.mkdir(parents=True)
    source = nested / "app.mm"
    source.write_text("implementation", encoding="utf-8")
    (project / "mumei.toml").write_text("[charter]\n", encoding="utf-8")
    _make_lock(tmp_path)
    assert CharterGuard.discover(str(source)) is None


def test_explicit_missing_lock_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        CharterGuard.discover(str(tmp_path / "app.mm"), str(tmp_path / "missing.lock"))


@pytest.mark.parametrize(
    ("contents", "error"),
    [
        ("{", "could not parse charter lock"),
        ('{"schema":"other","charters":[]}', "unsupported charter lock schema"),
    ],
)
def test_invalid_lock_raises(tmp_path: Path, contents: str, error: str) -> None:
    lock = tmp_path / "charter.lock"
    lock.write_text(contents, encoding="utf-8")
    with pytest.raises(ValueError, match=error):
        CharterGuard.discover(str(tmp_path / "app.mm"), str(lock))


@pytest.mark.parametrize("change", ["charter", "delete", "lock", "unchanged"])
def test_tampered_reports_changed_or_deleted_files(tmp_path: Path, change: str) -> None:
    lock = _make_lock(tmp_path)
    guard = CharterGuard.discover(str(tmp_path / "app.mm"), str(lock))
    assert guard is not None
    charter = tmp_path / "spec.charter.mm"
    if change == "charter":
        charter.write_text("changed", encoding="utf-8")
    elif change == "delete":
        charter.unlink()
    elif change == "lock":
        lock.write_text("changed", encoding="utf-8")
    assert bool(guard.tampered()) is (change != "unchanged")


def test_is_charter_file_accepts_relative_and_absolute_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = _make_lock(tmp_path)
    guard = CharterGuard.discover(str(tmp_path / "app.mm"), str(lock))
    assert guard is not None
    monkeypatch.chdir(tmp_path)
    assert guard.is_charter_file("spec.charter.mm")
    assert guard.is_charter_file(str((tmp_path / "spec.charter.mm").resolve()))
    assert not guard.is_charter_file("app.mm")


@pytest.mark.parametrize(
    ("result", "passed", "summary"),
    [
        (
            {
                "exit_code": 0,
                "report": {"status": "pass", "atoms": []},
                "stdout": "",
                "stderr": "",
            },
            True,
            "charter check passed",
        ),
        (
            {
                "exit_code": 1,
                "report": {
                    "status": "fail",
                    "atoms": [{"name": "f", "status": "post_weakened", "detail": "ensures"}],
                },
                "stdout": "",
                "stderr": "",
            },
            False,
            "f: post_weakened (ensures)",
        ),
        (
            {
                "exit_code": 0,
                "report": {"status": "fail", "atoms": []},
                "stdout": "not passing",
                "stderr": "",
            },
            False,
            "charter check failed (exit code 0): not passing",
        ),
        (
            {"exit_code": 2, "report": None, "stdout": "", "stderr": "unknown command"},
            False,
            "charter check failed (exit code 2): unknown command",
        ),
        (
            {"exit_code": 1, "report": None, "stdout": "not JSON", "stderr": ""},
            False,
            "charter check failed (exit code 1): not JSON",
        ),
    ],
)
def test_check_outcomes(
    tmp_path: Path, result: dict, passed: bool, summary: str
) -> None:
    lock = _make_lock(tmp_path)
    guard = CharterGuard.discover(str(tmp_path / "app.mm"), str(lock))
    assert guard is not None

    class FakeClient:
        def charter_check(
            self, source_path: str, lock_path: str, cwd: Path | None = None
        ) -> dict:
            assert Path(source_path).is_absolute()
            assert Path(lock_path) == lock.resolve()
            return result

    outcome = guard.check(FakeClient(), str(tmp_path / "app.mm"))
    assert outcome.passed is passed
    assert outcome.summary == summary


def test_config_charter_guard_defaults_and_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENABLE_CHARTER_GUARD", raising=False)
    monkeypatch.delenv("CHARTER_LOCK_PATH", raising=False)
    assert AgentConfig().enable_charter_guard is True
    assert AgentConfig().charter_lock_path is None
    monkeypatch.setenv("ENABLE_CHARTER_GUARD", "false")
    monkeypatch.setenv("CHARTER_LOCK_PATH", "explicit.lock")
    config = AgentConfig()
    assert config.enable_charter_guard is False
    assert config.charter_lock_path == "explicit.lock"
