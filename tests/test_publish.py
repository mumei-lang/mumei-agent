"""Tests for the publish pipeline (agent/publish.py)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from agent.publish import _sanitize_module_name, _validate_spec, publish


# --- _sanitize_module_name tests ---


class TestSanitizeModuleName:
    def test_valid_alphanumeric(self):
        assert _sanitize_module_name("my_module") == "my_module"

    def test_valid_with_dots_and_hyphens(self):
        assert _sanitize_module_name("my.module-v2") == "my.module-v2"

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="Unsafe module name"):
            _sanitize_module_name("")

    def test_rejects_slashes(self):
        with pytest.raises(ValueError, match="Unsafe module name"):
            _sanitize_module_name("../evil")

    def test_rejects_leading_hyphen(self):
        with pytest.raises(ValueError, match="Unsafe module name"):
            _sanitize_module_name("-A")

    def test_rejects_double_hyphen_flag(self):
        with pytest.raises(ValueError, match="Unsafe module name"):
            _sanitize_module_name("--help")

    def test_rejects_consecutive_dots(self):
        with pytest.raises(ValueError, match="Consecutive dots"):
            _sanitize_module_name("foo..bar")

    def test_rejects_leading_dot(self):
        with pytest.raises(ValueError, match="starting or ending with a dot"):
            _sanitize_module_name(".hidden")

    def test_rejects_trailing_dot(self):
        with pytest.raises(ValueError, match="starting or ending with a dot"):
            _sanitize_module_name("foo.")

    def test_rejects_dot_lock_suffix(self):
        with pytest.raises(ValueError, match=r"\.lock"):
            _sanitize_module_name("module.lock")


# --- _validate_spec tests ---


class TestValidateSpec:
    def test_valid_single_atom(self):
        assert _validate_spec({"name": "add", "params": []}) is None

    def test_valid_multi_atom(self):
        assert _validate_spec({"atoms": [{"name": "a"}]}) is None

    def test_missing_name(self):
        assert _validate_spec({"params": []}) is not None

    def test_empty_atoms(self):
        assert _validate_spec({"atoms": []}) is not None

    def test_atoms_entry_missing_name(self):
        error = _validate_spec({"atoms": [{"params": []}]})
        assert error is not None and "atoms[0]" in error


# --- Helpers ---

_CODE = "atom test_mod(x: i64) requires: x >= 0; body: x;"


def _spec_file(tmp_path, spec=None):
    spec = spec or {"name": "test_mod", "params": [{"name": "x", "type": "i64"}]}
    p = tmp_path / "spec.json"
    p.write_text(json.dumps(spec), encoding="utf-8")
    return str(p)


def _cfg():
    c = MagicMock()
    c.mumei_bin = "mumei"
    c.model = "test-model"
    c.max_retries = 2
    c.create_client.return_value = MagicMock()
    return c


def _cp(rc=0, out="", err=""):
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=out, stderr=err)


def _ok_client(MC):
    inst = MC.return_value
    inst.verify.return_value = {"success": True, "report": {}, "stdout": "", "stderr": ""}
    inst.build_with_emit.return_value = {"success": True, "stdout": "ok", "stderr": ""}
    return inst


# --- Dry-run tests ---


class TestPublishDryRun:
    def test_success(self, tmp_path):
        sp = _spec_file(tmp_path)
        with patch("agent.publish.AgentConfig", return_value=_cfg()), \
             patch("agent.publish.generate_code", return_value=(_CODE, True)), \
             patch("agent.publish.MumeiClient") as MC:
            _ok_client(MC)
            r = publish(spec_path=sp, repo_dir=str(tmp_path), dry_run=True)
        assert r["success"] is True
        assert r["generated_file"] == "test_mod.mm"
        assert r["verified_at_generation"] is True
        assert len(r["artifacts"]) == 3
        assert all(a["success"] is True for a in r["artifacts"])
        assert (tmp_path / "test_mod.mm").exists()

    def test_generation_failure(self, tmp_path):
        sp = _spec_file(tmp_path)
        with patch("agent.publish.AgentConfig", return_value=_cfg()), \
             patch("agent.publish.generate_code", return_value=("", False)), \
             patch("agent.publish.MumeiClient"):
            r = publish(spec_path=sp, dry_run=True)
        assert r["success"] is False
        assert r["generation_error"] == "empty code"

    def test_verify_failure(self, tmp_path):
        sp = _spec_file(tmp_path)
        with patch("agent.publish.AgentConfig", return_value=_cfg()), \
             patch("agent.publish.generate_code", return_value=(_CODE, False)), \
             patch("agent.publish.MumeiClient") as MC:
            MC.return_value.verify.return_value = {
                "success": False, "report": {}, "stdout": "", "stderr": "fail",
            }
            r = publish(spec_path=sp, repo_dir=str(tmp_path), dry_run=True)
        assert r["success"] is False
        assert "verify_error" in r

    def test_partial_emit_failure(self, tmp_path):
        sp = _spec_file(tmp_path)
        with patch("agent.publish.AgentConfig", return_value=_cfg()), \
             patch("agent.publish.generate_code", return_value=(_CODE, True)), \
             patch("agent.publish.MumeiClient") as MC:
            inst = MC.return_value
            inst.verify.return_value = {"success": True, "report": {}, "stdout": "", "stderr": ""}
            inst.build_with_emit.side_effect = [
                {"success": True, "stdout": "ok", "stderr": ""},
                {"success": False, "stdout": "", "stderr": "unsupported"},
                {"success": False, "stdout": "", "stderr": "unsupported"},
            ]
            r = publish(spec_path=sp, repo_dir=str(tmp_path), dry_run=True)
        assert r["success"] is True
        assert r["artifacts"][0]["success"] is True
        assert r["artifacts"][1]["success"] is False


# --- Spec validation tests ---


class TestPublishSpecValidation:
    def test_invalid_spec_missing_name(self, tmp_path):
        sp = _spec_file(tmp_path, spec={"params": []})
        with patch("agent.publish.AgentConfig", return_value=_cfg()), \
             patch("agent.publish.generate_code") as mg, \
             patch("agent.publish.MumeiClient"):
            r = publish(spec_path=sp, dry_run=True)
        assert r["success"] is False
        mg.assert_not_called()

    def test_unsafe_module_name(self, tmp_path):
        sp = _spec_file(tmp_path, spec={"name": "../evil"})
        with patch("agent.publish.AgentConfig", return_value=_cfg()), \
             patch("agent.publish.generate_code") as mg, \
             patch("agent.publish.MumeiClient"):
            r = publish(spec_path=sp, dry_run=True)
        assert r["success"] is False
        mg.assert_not_called()


# --- Git operations tests ---


class TestPublishGitOperations:
    def _run(self, tmp_path, git_fx, env=None):
        sp = _spec_file(tmp_path)
        with patch("agent.publish.AgentConfig", return_value=_cfg()), \
             patch("agent.publish.generate_code", return_value=(_CODE, True)), \
             patch("agent.publish.MumeiClient") as MC, \
             patch("agent.publish._git") as mg, \
             patch.dict("os.environ", env or {}, clear=False):
            _ok_client(MC)
            mg.side_effect = git_fx
            r = publish(spec_path=sp, repo_dir=str(tmp_path), dry_run=False)
        return r, mg

    def test_checkout_failure(self, tmp_path):
        r, _ = self._run(tmp_path, [
            _cp(0, out="develop"), _cp(1, err="branch exists"),
        ])
        assert r["success"] is False
        assert "branch exists" in r["git_error"]

    def test_commit_failure_restores_branch(self, tmp_path):
        r, mg = self._run(tmp_path, [
            _cp(0, out="develop"), _cp(0), _cp(0), _cp(0),
            _cp(1, err="nothing to commit"), _cp(0),
        ])
        assert r["success"] is False
        assert mg.call_args_list[-1] == call(["checkout", "develop"], cwd=tmp_path)

    def test_push_failure_restores_branch(self, tmp_path):
        r, mg = self._run(tmp_path, [
            _cp(0, out="main"), _cp(0), _cp(0), _cp(0),
            _cp(0), _cp(1, err="rejected"), _cp(0),
        ])
        assert r["success"] is False
        assert mg.call_args_list[-1] == call(["checkout", "main"], cwd=tmp_path)

    def test_add_uses_double_dash(self, tmp_path):
        r, mg = self._run(
            tmp_path,
            [_cp(0, out="dev")] + [_cp(0)] * 5,
            env={"GITHUB_TOKEN": "", "GITHUB_OWNER": "", "GITHUB_REPO": ""},
        )
        assert r["success"] is True
        add_calls = [c for c in mg.call_args_list if "add" in c[0][0]]
        for c in add_calls:
            assert "--" in c[0][0]

    def test_skips_pr_without_token(self, tmp_path):
        r, _ = self._run(
            tmp_path,
            [_cp(0, out="dev")] + [_cp(0)] * 5,
            env={"GITHUB_TOKEN": "", "GITHUB_OWNER": "", "GITHUB_REPO": ""},
        )
        assert r["success"] is True
        assert r["pr_url"] is None


# --- GitHub PR tests ---


class TestPublishGitHubPR:
    def test_pr_failure_still_succeeds(self, tmp_path):
        sp = _spec_file(tmp_path)
        env = {"GITHUB_TOKEN": "t", "GITHUB_OWNER": "o", "GITHUB_REPO": "r"}
        with patch("agent.publish.AgentConfig", return_value=_cfg()), \
             patch("agent.publish.generate_code", return_value=(_CODE, True)), \
             patch("agent.publish.MumeiClient") as MC, \
             patch("agent.publish._git") as mg, \
             patch("agent.publish._create_github_pr", side_effect=RuntimeError("API")), \
             patch.dict("os.environ", env, clear=False):
            _ok_client(MC)
            mg.side_effect = [_cp(0, out="dev")] + [_cp(0)] * 5
            r = publish(spec_path=sp, repo_dir=str(tmp_path), dry_run=False)
        assert r["success"] is True
        assert r["pr_created"] is False
        assert "API" in r["pr_error"]

    def test_pr_success(self, tmp_path):
        sp = _spec_file(tmp_path)
        env = {"GITHUB_TOKEN": "t", "GITHUB_OWNER": "o", "GITHUB_REPO": "r"}
        with patch("agent.publish.AgentConfig", return_value=_cfg()), \
             patch("agent.publish.generate_code", return_value=(_CODE, True)), \
             patch("agent.publish.MumeiClient") as MC, \
             patch("agent.publish._git") as mg, \
             patch("agent.publish._create_github_pr", return_value={"html_url": "https://pr/1"}), \
             patch.dict("os.environ", env, clear=False):
            _ok_client(MC)
            mg.side_effect = [_cp(0, out="dev")] + [_cp(0)] * 5
            r = publish(spec_path=sp, repo_dir=str(tmp_path), dry_run=False)
        assert r["success"] is True
        assert r["pr_created"] is True
        assert r["pr_url"] == "https://pr/1"


# --- Full pipeline dry-run tests ---


class TestPublishDryRunFullPipeline:
    """Test the complete dry-run pipeline with all emit targets."""

    def test_publish_emit_targets_called(self, tmp_path):
        """Verify build_with_emit is called exactly 3 times with correct targets."""
        sp = _spec_file(tmp_path)
        with patch("agent.publish.AgentConfig", return_value=_cfg()), \
             patch("agent.publish.generate_code", return_value=(_CODE, True)), \
             patch("agent.publish.MumeiClient") as MC:
            inst = _ok_client(MC)
            publish(spec_path=sp, repo_dir=str(tmp_path), dry_run=True)
        assert inst.build_with_emit.call_count == 3
        called_targets = [c[0][1] for c in inst.build_with_emit.call_args_list]
        assert called_targets == ["c-header", "rust-wrapper", "python-wrapper"]

    def test_publish_verification_failure_aborts(self, tmp_path):
        """Verify that a verification failure aborts the pipeline."""
        sp = _spec_file(tmp_path)
        with patch("agent.publish.AgentConfig", return_value=_cfg()), \
             patch("agent.publish.generate_code", return_value=(_CODE, False)), \
             patch("agent.publish.MumeiClient") as MC:
            MC.return_value.verify.return_value = {
                "success": False, "report": {}, "stdout": "", "stderr": "proof failed",
            }
            r = publish(spec_path=sp, repo_dir=str(tmp_path), dry_run=True)
        assert r["success"] is False
        assert r.get("verify_error") is not None

    def test_publish_git_branch_naming(self, tmp_path):
        """Verify the branch name follows auto/<module_name> convention."""
        sp = _spec_file(tmp_path)
        with patch("agent.publish.AgentConfig", return_value=_cfg()), \
             patch("agent.publish.generate_code", return_value=(_CODE, True)), \
             patch("agent.publish.MumeiClient") as MC, \
             patch("agent.publish._git") as mg, \
             patch.dict("os.environ", {"GITHUB_TOKEN": "", "GITHUB_OWNER": "", "GITHUB_REPO": ""}, clear=False):
            _ok_client(MC)
            mg.side_effect = [_cp(0, out="develop")] + [_cp(0)] * 5
            publish(spec_path=sp, repo_dir=str(tmp_path), dry_run=False)
        # Find the checkout -b call and verify branch name
        checkout_calls = [
            c for c in mg.call_args_list
            if len(c[0][0]) >= 3 and c[0][0][0] == "checkout" and c[0][0][1] == "-b"
        ]
        assert len(checkout_calls) == 1
        assert checkout_calls[0][0][0][2] == "auto/test_mod"


# --- MUMEI_BIN fallback tests ---


class TestMumeiBinFallback:
    def test_uses_config_when_none(self, tmp_path):
        sp = _spec_file(tmp_path)
        cfg = _cfg()
        cfg.mumei_bin = "/custom/mumei"
        with patch("agent.publish.AgentConfig", return_value=cfg), \
             patch("agent.publish.generate_code", return_value=(_CODE, True)), \
             patch("agent.publish.MumeiClient") as MC:
            _ok_client(MC)
            publish(spec_path=sp, mumei_bin=None, repo_dir=str(tmp_path), dry_run=True)
        MC.assert_called_once_with("/custom/mumei")

    def test_explicit_overrides_config(self, tmp_path):
        sp = _spec_file(tmp_path)
        cfg = _cfg()
        cfg.mumei_bin = "/default/mumei"
        with patch("agent.publish.AgentConfig", return_value=cfg), \
             patch("agent.publish.generate_code", return_value=(_CODE, True)), \
             patch("agent.publish.MumeiClient") as MC:
            _ok_client(MC)
            publish(spec_path=sp, mumei_bin="/explicit", repo_dir=str(tmp_path), dry_run=True)
        MC.assert_called_once_with("/explicit")
