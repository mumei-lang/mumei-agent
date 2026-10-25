from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from agent.erosion_guard import ErosionGuard, create_guard
from agent.mcp_client import MumeiMCPClient
from agent.mumei_client import MumeiClient


def _source(tmp_path: Path) -> Path:
    source = tmp_path / "source.mm"
    source.write_bytes(b"original source\n")
    return source


def _client(result: dict) -> MagicMock:
    client = MagicMock()
    client.erosion_check.return_value = result
    return client


def test_guard_snapshots_original_bytes_outside_project(tmp_path):
    source = _source(tmp_path)
    guard = ErosionGuard.create(source)
    try:
        source.write_bytes(b"candidate source\n")
        assert guard.baseline_path.read_bytes() == b"original source\n"
        assert tmp_path not in guard.baseline_path.parents
    finally:
        guard.close()


def test_guard_passes_parsed_report(tmp_path):
    guard = ErosionGuard.create(_source(tmp_path))
    try:
        report = {"status": "pass", "atoms": []}
        outcome = guard.check(
            _client({"returncode": 0, "report": report, "stderr": ""}),
            str(tmp_path / "source.mm"),
        )
        assert outcome.passed and not outcome.skipped
        assert outcome.report == report
    finally:
        guard.close()


def test_guard_failure_summary_includes_atom_status_and_counterexample(tmp_path):
    guard = ErosionGuard.create(_source(tmp_path))
    try:
        report = {
            "status": "fail",
            "atoms": [
                {
                    "name": "clamp",
                    "status": "post_weakened",
                    "detail": "upper bound dropped",
                    "counterexample": "x = 3",
                }
            ],
        }
        outcome = guard.check(
            _client({"returncode": 1, "report": report, "stderr": ""}),
            str(tmp_path / "source.mm"),
        )
        assert not outcome.passed
        assert "clamp: post_weakened (upper bound dropped)" in outcome.summary
        assert "x = 3" in outcome.summary
    finally:
        guard.close()


def test_guard_old_mumei_warns_once(capsys, tmp_path):
    guard = ErosionGuard.create(_source(tmp_path))
    try:
        client = _client(
            {
                "returncode": 2,
                "report": None,
                "stderr": "error: unrecognized subcommand 'erosion'",
            }
        )
        assert guard.check(client, str(tmp_path / "source.mm")).skipped
        assert guard.check(client, str(tmp_path / "source.mm")).skipped
        assert capsys.readouterr().err == (
            "mumei erosion unavailable; skipping contract erosion check\n"
        )
    finally:
        guard.close()


def test_guard_exit_four_skips_with_stderr_warning(capsys, tmp_path):
    guard = ErosionGuard.create(_source(tmp_path))
    try:
        outcome = guard.check(
            _client({"returncode": 4, "report": None, "stderr": "bad baseline"}),
            str(tmp_path / "source.mm"),
        )
        assert outcome.passed and outcome.skipped
        assert "bad baseline" in capsys.readouterr().err
    finally:
        guard.close()


def test_guard_fails_closed_for_other_exit_codes_and_malformed_json(tmp_path):
    cases = [
        {"returncode": 3, "report": None, "stderr": "error"},
        {"returncode": 0, "report": None, "stderr": ""},
        {"returncode": 1, "report": None, "stderr": ""},
    ]
    for result in cases:
        guard = ErosionGuard.create(_source(tmp_path))
        try:
            outcome = guard.check(_client(result), str(tmp_path / "source.mm"))
            assert not outcome.passed
            assert outcome.summary == "erosion check returned malformed output"
        finally:
            guard.close()


def test_guard_close_removes_temporary_directory(tmp_path):
    guard = ErosionGuard.create(_source(tmp_path))
    baseline_dir = guard.baseline_path.parent
    assert baseline_dir.exists()
    guard.close()
    assert not baseline_dir.exists()


def test_disabled_guard_is_not_created(tmp_path):
    assert create_guard(_source(tmp_path), enabled=False) is None


def test_guard_is_not_created_for_missing_source(tmp_path):
    assert create_guard(tmp_path / "not-yet-generated.mm", enabled=True) is None


def test_erosion_check_constructs_plain_binary_command(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    client = MumeiClient("mumei")
    with patch("agent.mumei_client.subprocess.run") as run:
        run.return_value = MagicMock(
            returncode=0, stdout='{"status":"pass"}', stderr=""
        )
        result = client.erosion_check("candidate.mm", "baseline.mm")
    assert run.call_args.args[0] == [
        "mumei",
        "erosion",
        "candidate.mm",
        "--baseline",
        "baseline.mm",
        "--json",
    ]
    assert result == {
        "returncode": 0,
        "report": {"status": "pass"},
        "stderr": "",
    }


def test_erosion_check_adds_cargo_manifest_when_missing(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "Cargo.toml").write_text("[package]\nname='mumei'\n")
    client = MumeiClient("cargo run --")
    with patch("agent.mumei_client.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout="{}", stderr="")
        client.erosion_check("candidate.mm", "baseline.mm")
    assert run.call_args.args[0][:5] == [
        "cargo",
        "run",
        "--manifest-path",
        str((tmp_path / "Cargo.toml").resolve()),
        "--",
    ]
    assert run.call_args.args[0][5:] == [
        "erosion",
        "candidate.mm",
        "--baseline",
        "baseline.mm",
        "--json",
    ]


def test_erosion_check_preserves_existing_cargo_manifest_forms(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "Cargo.toml").write_text("[package]\nname='mumei'\n")
    cases = (
        (
            "cargo run --manifest-path project/Cargo.toml --",
            ["cargo", "run", "--manifest-path", "project/Cargo.toml", "--"],
        ),
        (
            "cargo run --manifest-path=project/Cargo.toml --",
            ["cargo", "run", "--manifest-path=project/Cargo.toml", "--"],
        ),
    )
    for prefix, expected_prefix in cases:
        client = MumeiClient(prefix)
        with patch("agent.mumei_client.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0, stdout="{}", stderr="")
            client.erosion_check("candidate.mm", "baseline.mm")
        command = run.call_args.args[0]
        assert command[: len(expected_prefix)] == expected_prefix
        assert command[-5:] == [
            "erosion",
            "candidate.mm",
            "--baseline",
            "baseline.mm",
            "--json",
        ]


def test_erosion_check_resolves_relative_binary(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    client = MumeiClient("./tools/mumei")
    with patch("agent.mumei_client.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout="{}", stderr="")
        client.erosion_check("candidate.mm", "baseline.mm")
    assert run.call_args.args[0][0] == str((tmp_path / "tools/mumei").resolve())


def test_mcp_erosion_check_delegates_to_cli_fallback():
    fallback = MagicMock()
    expected = {"returncode": 1, "report": {"status": "fail"}, "stderr": ""}
    fallback.erosion_check.return_value = expected
    client = MumeiMCPClient(fallback_client=fallback)
    assert client.erosion_check("candidate.mm", "baseline.mm") == expected
    fallback.erosion_check.assert_called_once_with("candidate.mm", "baseline.mm")
