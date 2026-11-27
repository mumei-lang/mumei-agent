from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ACTION_PATH = ROOT / ".github" / "actions" / "mumei-audit" / "action.yml"
SUMMARY_SCRIPT = ROOT / ".github" / "actions" / "mumei-audit" / "scripts" / "summarize_audit.py"
SELFTEST_PATH = ROOT / ".github" / "workflows" / "mumei-audit-selftest.yml"


def _action() -> dict:
    return yaml.safe_load(ACTION_PATH.read_text(encoding="utf-8"))


def test_composite_action_contract_and_cache_steps() -> None:
    action = _action()

    assert action["runs"]["using"] == "composite"
    inputs = action["inputs"]
    assert inputs["code-file"]["required"] is True
    assert inputs["mumei-version"]["default"] == "latest"
    assert inputs["upload-sarif"]["type"] == "boolean"
    for output in ("audit_exit_code", "setup_seconds", "audit_seconds", "total_seconds"):
        assert output in action["outputs"]

    steps = action["runs"]["steps"]
    names = [step["name"] for step in steps]
    for required in (
        "Install mumei",
        "Set up uv with dependency cache",
        "Install mumei-agent dependencies",
        "Run mumei-agent audit",
        "Write step summary and timing outputs",
        "Upload SARIF to code scanning",
    ):
        assert required in names
    setup_uv = next(step for step in steps if step["name"] == "Set up uv with dependency cache")
    assert setup_uv["uses"] == "astral-sh/setup-uv@v5"
    assert setup_uv["with"]["enable-cache"] is True
    assert setup_uv["with"]["cache-dependency-glob"] == "${{ env.AGENT_ROOT }}/uv.lock"
    assert 'MUMEI_STD_PATH=$HOME/.mumei/std' in ACTION_PATH.read_text(encoding="utf-8")
    audit_step = next(step for step in steps if step["name"] == "Run mumei-agent audit")
    assert "--sarif-output" in audit_step["run"]
    assert "audit_exit_code" in audit_step["run"]
    artifact_step = next(step for step in steps if step["name"] == "Upload audit evidence artifact")
    assert artifact_step["with"]["include-hidden-files"] is True
    assert artifact_step["if"] == "always() && steps.audit.outputs.audit_exit_code != ''"
    assert "${{ runner.temp }}/mumei-audit" in artifact_step["with"]["path"]
    assert "UV_PROJECT=" in audit_step["run"]
    assert "prepare_output_path" in audit_step["run"]
    assert "mumei-agent-uv.lock" not in ACTION_PATH.read_text(encoding="utf-8")


def test_action_does_not_embed_secret_values_or_secret_env_names() -> None:
    text = ACTION_PATH.read_text(encoding="utf-8")

    assert "LLM_API_KEY" not in text
    assert "OPENAI_API_KEY" not in text
    assert "secrets." not in text
    assert "sk-" not in text


def test_selftest_workflow_exercises_small_repo_and_publishes_timing() -> None:
    workflow = yaml.safe_load(SELFTEST_PATH.read_text(encoding="utf-8"))

    assert workflow["permissions"]["security-events"] == "write"
    steps = workflow["jobs"]["small-repo"]["steps"]
    action_step = next(step for step in steps if step.get("uses") == "./.github/actions/mumei-audit")
    assert action_step["with"]["code-file"] == "examples/ci-small-repo/src"
    assert action_step["with"]["language"] == "python"
    audit_args = action_step["with"]["audit-args"]
    assert "--baseline examples/ci-small-repo/baseline.json" in audit_args
    assert "--write-baseline .mumei-audit/generated-baseline.json" in audit_args
    assert "--fail-on high-confidence" in audit_args
    baseline = json.loads((ROOT / "examples" / "ci-small-repo" / "baseline.json").read_text(encoding="utf-8"))
    assert baseline == {"version": "mumei.audit-baseline/v1", "fingerprints": []}
    publish = next(step for step in steps if step.get("name") == "Publish measured action runtime")
    assert "setup_seconds" in publish["run"]
    assert "audit_seconds" in publish["run"]
    assert "total_seconds" in publish["run"]


def test_composite_run_scripts_have_valid_bash_syntax(tmp_path: Path) -> None:
    action = _action()

    for index, step in enumerate(action["runs"]["steps"]):
        script = step.get("run")
        if not script:
            continue
        probe = tmp_path / f"step-{index}.sh"
        probe.write_text(re.sub(r"\$\{\{[^}]*\}\}", "x", script), encoding="utf-8")
        result = subprocess.run(["bash", "-n", str(probe)], capture_output=True, text=True)
        assert result.returncode == 0, f"{step.get('name')}: {result.stderr}"


def test_prepare_output_path_rejects_symlink_parent_and_replaces_leaf_symlink(tmp_path: Path) -> None:
    helper = SUMMARY_SCRIPT.parent / "prepare_output_path.py"
    target = tmp_path / "target"
    target.mkdir()
    link_parent = tmp_path / "link-parent"
    link_parent.symlink_to(target, target_is_directory=True)
    rejected = subprocess.run(
        [sys.executable, str(helper), str(link_parent / "audit.json")],
        capture_output=True,
        text=True,
    )
    assert rejected.returncode != 0

    output = tmp_path / "audit.json"
    victim = tmp_path / "victim.json"
    victim.write_text("keep\n", encoding="utf-8")
    output.symlink_to(victim)
    subprocess.run([sys.executable, str(helper), str(output)], check=True)
    assert not output.is_symlink()
    assert victim.read_text(encoding="utf-8") == "keep\n"


def test_summarize_audit_writes_step_summary_and_timing_outputs(tmp_path: Path) -> None:
    audit_json = tmp_path / "audit.json"
    audit_json.write_text(
        json.dumps(
            {
                "verification_status": "refuted",
                "finding_counts": {"code": 1, "confirmed": 1, "spec": 2, "model_limitations": 0, "errors": 0},
                "verification_violations": ["division by zero is reachable"],
                "cross_validation_gaps": ["requires is missing"],
                "next_steps": [{"priority": "high", "action": "review", "command": "mumei-agent audit"}],
            }
        ),
        encoding="utf-8",
    )
    timing = tmp_path / "timing"
    timing.mkdir()
    (timing / "start").write_text("100\n", encoding="utf-8")
    (timing / "setup_end").write_text("112\n", encoding="utf-8")
    (timing / "audit_start").write_text("113\n", encoding="utf-8")
    (timing / "audit_end").write_text("141\n", encoding="utf-8")
    summary = tmp_path / "summary.md"
    output = tmp_path / "github-output"
    env = {**os.environ, "GITHUB_STEP_SUMMARY": str(summary)}

    subprocess.run(
        [
            sys.executable,
            str(SUMMARY_SCRIPT),
            "--audit-json",
            str(audit_json),
            "--exit-code",
            "1",
            "--timing-dir",
            str(timing),
            "--github-output",
            str(output),
        ],
        env=env,
        check=True,
    )

    text = summary.read_text(encoding="utf-8")
    assert "verification_status: `refuted`" in text
    assert "division by zero is reachable" in text
    assert "setup `12s`, audit `28s`, total `41s`" in text
    assert output.read_text(encoding="utf-8") == "setup_seconds=12\naudit_seconds=28\ntotal_seconds=41\n"


def test_summarize_audit_tolerates_missing_or_malformed_audit_json(tmp_path: Path) -> None:
    timing = tmp_path / "timing"
    timing.mkdir()
    summary = tmp_path / "summary.md"
    env = {**os.environ, "GITHUB_STEP_SUMMARY": str(summary)}

    subprocess.run(
        [
            sys.executable,
            str(SUMMARY_SCRIPT),
            "--audit-json",
            str(tmp_path / "missing.json"),
            "--exit-code",
            "2",
            "--timing-dir",
            str(timing),
        ],
        env=env,
        check=True,
    )

    assert "Audit JSON was not produced or was malformed" in summary.read_text(encoding="utf-8")
