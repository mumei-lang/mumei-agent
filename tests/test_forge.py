"""Unit tests for agent.forge (MumeiForge orchestrator)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.forge import ForgeResult, MumeiForge


# --- Helpers ----------------------------------------------------------------


def _make_config():
    cfg = MagicMock()
    cfg.mumei_bin = "mumei"
    cfg.model = "test-model"
    cfg.max_retries = 2
    cfg.create_client.return_value = MagicMock()
    return cfg


def _make_mumei(verify_success=True, check_success=True):
    m = MagicMock()
    m.verify.return_value = {
        "success": verify_success,
        "report": {} if verify_success else {"status": "failed"},
        "stdout": "",
        "stderr": "" if verify_success else "fail",
    }
    m.check.return_value = {
        "success": check_success,
        "stdout": "",
        "stderr": "" if check_success else "parse error",
    }
    return m


def _make_openai_response(text: str):
    client = MagicMock()
    message = MagicMock()
    message.content = text
    choice = MagicMock()
    choice.message = message
    resp = MagicMock()
    resp.choices = [choice]
    client.chat.completions.create.return_value = resp
    return client


def _make_forge(tmp_path, *, repo_dir=None, tasks_dir=None, mumei=None, client=None):
    repo = Path(repo_dir) if repo_dir else tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    tasks = Path(tasks_dir) if tasks_dir else tmp_path / "forge_tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    return MumeiForge(
        config=_make_config(),
        mumei_client=mumei or _make_mumei(),
        mumei_repo_dir=repo,
        forge_tasks_dir=tasks,
        log_path=tmp_path / "forge_log.json",
        openai_client=client,
    )


def _cp(rc=0, out="", err=""):
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=out, stderr=err)


_TARGET_BEFORE = (
    "// std/contracts.mm\n\n"
    "atom safe_subtract(a: i64, b: i64)\n"
    "    requires: a >= b;\n"
    "    ensures: result >= 0 && result == a - b;\n"
    "    body: a - b;\n"
)

_APPEND_SNIPPET = (
    "atom safe_add(a: i64, b: i64)\n"
    "    requires: a >= 0 && b >= 0;\n"
    "    ensures: result >= 0 && result == a + b;\n"
    "    body: a + b;\n"
)


# --- ForgeResult ------------------------------------------------------------


class TestForgeResult:
    def test_to_dict_roundtrip(self):
        r = ForgeResult(
            task_id="t", status="success", attempts=3,
            target_file="std/x.mm", atoms_added=["foo"], commit_sha="abc",
        )
        d = r.to_dict()
        assert d["task_id"] == "t"
        assert d["status"] == "success"
        assert d["atoms_added"] == ["foo"]
        assert d["commit_sha"] == "abc"


# --- forge_one: append mode -------------------------------------------------


class TestForgeOneAppend:
    def _task(self):
        return {
            "task_id": "vstd-contracts-safe-add",
            "target_file": "std/contracts.mm",
            "mode": "append",
            "atoms": [{
                "name": "safe_add",
                "inputs": [{"name": "a", "type": "i64"}, {"name": "b", "type": "i64"}],
                "requires": "a >= 0 && b >= 0",
                "ensures": "result == a + b",
                "reference_patterns": ["safe_subtract"],
            }],
            "max_retries": 2,
            "auto_commit": False,
        }

    def _setup_target(self, forge):
        target = forge.mumei_repo_dir / "std" / "contracts.mm"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_TARGET_BEFORE, encoding="utf-8")
        return target

    def test_success(self, tmp_path):
        mumei = _make_mumei(verify_success=True, check_success=True)
        client = _make_openai_response(f"```mumei\n{_APPEND_SNIPPET}```")
        forge = _make_forge(tmp_path, mumei=mumei, client=client)
        target = self._setup_target(forge)

        result = forge.forge_one(self._task())

        assert result.status == "success"
        assert result.atoms_added == ["safe_add"]
        assert result.attempts == 1
        text = target.read_text(encoding="utf-8")
        assert "safe_subtract" in text  # preserved
        assert "safe_add" in text       # appended

    def test_verify_failure_restores_original(self, tmp_path):
        mumei = _make_mumei(verify_success=False, check_success=True)
        client = _make_openai_response(f"```mumei\n{_APPEND_SNIPPET}```")
        forge = _make_forge(tmp_path, mumei=mumei, client=client)
        target = self._setup_target(forge)

        task = self._task()
        task["max_retries"] = 2

        result = forge.forge_one(task)

        assert result.status == "failed"
        assert result.attempts == 2
        # Original source restored
        assert target.read_text(encoding="utf-8") == _TARGET_BEFORE

    def test_missing_target_file(self, tmp_path):
        forge = _make_forge(tmp_path)
        task = self._task()
        # Do NOT create target file.
        result = forge.forge_one(task)
        assert result.status == "failed"
        assert "FileNotFoundError" in (result.error or "") or "requires existing" in (result.error or "")

    def test_rejects_path_outside_repo(self, tmp_path):
        forge = _make_forge(tmp_path)
        task = {
            "task_id": "evil",
            "target_file": "../escape.mm",
            "mode": "append",
            "atoms": [{"name": "x"}],
        }
        result = forge.forge_one(task)
        assert result.status == "failed"
        assert "escapes repo root" in (result.error or "")

    def test_empty_atoms(self, tmp_path):
        forge = _make_forge(tmp_path)
        task = {"task_id": "t", "target_file": "x.mm", "mode": "append", "atoms": []}
        result = forge.forge_one(task)
        assert result.status == "failed"
        assert "no atoms" in (result.error or "")

    def test_unknown_mode(self, tmp_path):
        forge = _make_forge(tmp_path)
        task = {
            "task_id": "t", "target_file": "x.mm",
            "mode": "bogus", "atoms": [{"name": "a"}],
        }
        result = forge.forge_one(task)
        assert result.status == "failed"
        assert "unknown mode" in (result.error or "")

    def test_retries_on_parse_failure(self, tmp_path):
        """The second attempt should succeed after an initial parse failure."""
        mumei = _make_mumei()
        # First check fails, second succeeds
        mumei.check.side_effect = [
            {"success": False, "stdout": "", "stderr": "parse err"},
            {"success": True, "stdout": "", "stderr": ""},
        ]
        mumei.verify.return_value = {"success": True, "report": {}, "stdout": "", "stderr": ""}
        client = _make_openai_response(f"```mumei\n{_APPEND_SNIPPET}```")
        forge = _make_forge(tmp_path, mumei=mumei, client=client)
        self._setup_target(forge)

        task = self._task()
        task["max_retries"] = 3
        result = forge.forge_one(task)
        assert result.status == "success"
        assert result.attempts == 2

    def test_error_feedback_passed_to_llm_on_retry(self, tmp_path):
        """Verify/check errors should be fed back to the LLM on the next attempt."""
        mumei = _make_mumei()
        mumei.check.side_effect = [
            {"success": True, "stdout": "", "stderr": ""},
            {"success": True, "stdout": "", "stderr": ""},
        ]
        mumei.verify.side_effect = [
            {"success": False, "report": {}, "stdout": "", "stderr": "ensures violated: result >= 0"},
            {"success": True, "report": {}, "stdout": "", "stderr": ""},
            # post-write verify
            {"success": True, "report": {}, "stdout": "", "stderr": ""},
        ]
        client = _make_openai_response(f"```mumei\n{_APPEND_SNIPPET}```")
        forge = _make_forge(tmp_path, mumei=mumei, client=client)
        self._setup_target(forge)

        task = self._task()
        task["max_retries"] = 3
        result = forge.forge_one(task)
        assert result.status == "success"
        assert result.attempts == 2

        # The second LLM call should contain the error from the first attempt.
        calls = client.chat.completions.create.call_args_list
        assert len(calls) == 2
        second_prompt = calls[1].kwargs["messages"][1]["content"]
        assert "ensures violated" in second_prompt
        assert "Previous attempt" in second_prompt or "previous attempt" in second_prompt

    def test_auto_commit_invokes_git(self, tmp_path):
        mumei = _make_mumei(verify_success=True, check_success=True)
        client = _make_openai_response(f"```mumei\n{_APPEND_SNIPPET}```")
        forge = _make_forge(tmp_path, mumei=mumei, client=client)
        self._setup_target(forge)

        task = self._task()
        task["auto_commit"] = True

        with patch("agent.forge._git") as mg, \
             patch("agent.forge._ensure_git_identity") as mid:
            mg.side_effect = [_cp(0), _cp(0), _cp(0, out="abc123\n")]
            result = forge.forge_one(task)

        assert result.status == "success"
        assert result.commit_sha == "abc123"
        mid.assert_called_once_with(forge.mumei_repo_dir)
        # add, commit, rev-parse
        assert mg.call_count == 3
        assert mg.call_args_list[0][0][0][0] == "add"
        assert mg.call_args_list[1][0][0][0] == "commit"
        assert mg.call_args_list[2][0][0][0] == "rev-parse"

    def test_auto_commit_rejects_unsafe_task_id(self, tmp_path):
        mumei = _make_mumei(verify_success=True, check_success=True)
        client = _make_openai_response(f"```mumei\n{_APPEND_SNIPPET}```")
        forge = _make_forge(tmp_path, mumei=mumei, client=client)
        self._setup_target(forge)

        task = self._task()
        task["task_id"] = "evil;rm -rf /"
        task["auto_commit"] = True

        with patch("agent.forge._git") as mg, \
             patch("agent.forge._ensure_git_identity") as mid:
            result = forge.forge_one(task)

        assert result.status == "success"
        assert result.commit_sha is None
        mg.assert_not_called()
        mid.assert_not_called()


# --- forge_one: create/replace modes ----------------------------------------


class TestForgeOneModule:
    def test_create_writes_module(self, tmp_path):
        forge = _make_forge(tmp_path)
        task = {
            "task_id": "new-mod",
            "target_file": "std/newmod.mm",
            "mode": "create",
            "atoms": [{"name": "f", "requires": "true", "ensures": "true"}],
            "max_retries": 2,
        }
        with patch("agent.forge.generate_code", return_value=("atom f() requires: true; ensures: true; body: 1;", True)):
            result = forge.forge_one(task)
        assert result.status == "success"
        target = forge.mumei_repo_dir / "std" / "newmod.mm"
        assert target.exists()
        assert "atom f" in target.read_text(encoding="utf-8")

    def test_create_refuses_if_exists(self, tmp_path):
        forge = _make_forge(tmp_path)
        target = forge.mumei_repo_dir / "std" / "existing.mm"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("atom x() requires: true; ensures: true; body: 0;", encoding="utf-8")
        task = {
            "task_id": "new-mod",
            "target_file": "std/existing.mm",
            "mode": "create",
            "atoms": [{"name": "f"}],
        }
        result = forge.forge_one(task)
        assert result.status == "failed"
        assert "FileExistsError" in (result.error or "") or "non-existent" in (result.error or "")

    def test_generate_code_failure(self, tmp_path):
        forge = _make_forge(tmp_path)
        task = {
            "task_id": "new-mod",
            "target_file": "std/x.mm",
            "mode": "create",
            "atoms": [{"name": "f"}],
        }
        with patch("agent.forge.generate_code", return_value=("", False)):
            result = forge.forge_one(task)
        assert result.status == "failed"


# --- run() / dry_run / logging ---------------------------------------------


class TestRun:
    def test_dry_run_prints_plan_and_returns_skipped(self, tmp_path, capsys):
        tasks_dir = tmp_path / "forge_tasks"
        tasks_dir.mkdir()
        (tasks_dir / "a.json").write_text(json.dumps({
            "task_id": "t1", "target_file": "std/a.mm",
            "atoms": [{"name": "a"}], "priority": 1,
        }), encoding="utf-8")

        forge = _make_forge(tmp_path, tasks_dir=tasks_dir)
        results = forge.run(dry_run=True)

        assert len(results) == 1
        assert results[0].status == "skipped"
        out = capsys.readouterr().out
        assert "Forge plan" in out
        assert "t1" in out

    def test_max_tasks_caps(self, tmp_path):
        tasks_dir = tmp_path / "forge_tasks"
        tasks_dir.mkdir()
        for i in range(3):
            (tasks_dir / f"t{i}.json").write_text(json.dumps({
                "task_id": f"t{i}", "target_file": "x", "priority": i,
                "atoms": [{"name": "a"}],
            }), encoding="utf-8")

        forge = _make_forge(tmp_path, tasks_dir=tasks_dir)
        results = forge.run(dry_run=True, max_tasks=2)
        assert len(results) == 2

    def test_single_task_path(self, tmp_path):
        spec = tmp_path / "solo.json"
        spec.write_text(json.dumps({
            "task_id": "solo", "target_file": "std/x.mm",
            "atoms": [{"name": "a"}],
        }), encoding="utf-8")
        forge = _make_forge(tmp_path)
        results = forge.run(dry_run=True, single_task_path=spec)
        assert len(results) == 1
        assert results[0].task_id == "solo"

    def test_log_result_appends(self, tmp_path):
        forge = _make_forge(tmp_path)
        forge.log_result(
            {"task_id": "t1", "_spec_path": "/x/a.json"},
            ForgeResult(task_id="t1", status="success", attempts=2,
                        target_file="std/a.mm", atoms_added=["a"], commit_sha="deadbeef"),
        )
        forge.log_result(
            {"task_id": "t2", "_spec_path": "/x/b.json"},
            ForgeResult(task_id="t2", status="failed", attempts=5, error="boom"),
        )
        data = json.loads(forge.log_path.read_text(encoding="utf-8"))
        assert [r["task_id"] for r in data["runs"]] == ["t1", "t2"]
        assert data["runs"][0]["atoms_added"] == ["a"]
        assert data["runs"][0]["commit_sha"] == "deadbeef"
        assert data["runs"][0]["timestamp"]
        assert data["runs"][1]["error"] == "boom"

    def test_skips_completed_tasks(self, tmp_path):
        tasks_dir = tmp_path / "forge_tasks"
        tasks_dir.mkdir()
        (tasks_dir / "done.json").write_text(json.dumps({
            "task_id": "done", "target_file": "x", "priority": 1,
            "atoms": [{"name": "a"}],
        }), encoding="utf-8")
        (tasks_dir / "new.json").write_text(json.dumps({
            "task_id": "new", "target_file": "x", "priority": 2,
            "atoms": [{"name": "a"}],
        }), encoding="utf-8")

        log = tmp_path / "forge_log.json"
        log.write_text(json.dumps({"runs": [
            {"task_id": "done", "status": "success"},
        ]}), encoding="utf-8")

        forge = _make_forge(tmp_path, tasks_dir=tasks_dir)
        results = forge.run(dry_run=True)
        assert [r.task_id for r in results] == ["new"]

    def test_dry_run_works_without_api_key(self, tmp_path, monkeypatch, capsys):
        """`python -m agent forge --dry-run` must not require OPENAI_API_KEY.

        The README advertises --dry-run as a no-dependency preview, and
        `AgentConfig.create_client()` raises ValueError when neither
        LLM_API_KEY nor OPENAI_API_KEY is set.  Regression guard for
        https://github.com/mumei-lang/mumei-agent/pull/31 review feedback.
        """
        from agent.forge import main as forge_main

        # Simulate an environment with no LLM credentials configured.
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        tasks_dir = tmp_path / "forge_tasks"
        tasks_dir.mkdir()
        (tasks_dir / "a.json").write_text(json.dumps({
            "task_id": "dry-run-probe",
            "target_file": "std/a.mm",
            "priority": 1,
            "atoms": [{"name": "a"}],
        }), encoding="utf-8")

        args = MagicMock()
        args.tasks_dir = str(tasks_dir)
        args.mumei_repo = str(tmp_path)
        args.max_tasks = None
        args.task = None
        args.dry_run = True
        args.auto_commit = None
        args.max_retries = None
        args.log_path = str(tmp_path / "forge_log.json")

        # Must not raise.
        forge_main(args)

        out = capsys.readouterr().out
        assert "Forge plan" in out
        assert "dry-run-probe" in out

    def test_auto_commit_override(self, tmp_path):
        """auto_commit_override should force the flag regardless of spec."""
        tasks_dir = tmp_path / "forge_tasks"
        tasks_dir.mkdir()
        (tasks_dir / "a.json").write_text(json.dumps({
            "task_id": "t", "target_file": "std/a.mm",
            "atoms": [{"name": "safe_add",
                       "inputs": [{"name": "a", "type": "i64"}],
                       "reference_patterns": ["safe_subtract"]}],
            "auto_commit": False,
        }), encoding="utf-8")

        mumei = _make_mumei(verify_success=True, check_success=True)
        client = _make_openai_response(f"```mumei\n{_APPEND_SNIPPET}```")
        forge = _make_forge(tmp_path, tasks_dir=tasks_dir, mumei=mumei, client=client)
        target = forge.mumei_repo_dir / "std" / "a.mm"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_TARGET_BEFORE, encoding="utf-8")

        with patch("agent.forge._git") as mg, \
             patch("agent.forge._ensure_git_identity"):
            mg.side_effect = [_cp(0), _cp(0), _cp(0, out="sha\n")]
            results = forge.run(auto_commit_override=True)

        assert len(results) == 1
        assert results[0].status == "success"
        assert results[0].commit_sha == "sha"
