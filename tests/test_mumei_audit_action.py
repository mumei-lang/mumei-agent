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
VERIFY_ARTIFACT_SCRIPT = ROOT / ".github" / "actions" / "mumei-audit" / "scripts" / "verify_audit_evidence_artifact.py"
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
    assert artifact_step["if"] == "always()"
    assert artifact_step["with"]["path"] == "${{ env.ACTION_STATE }}"
    assert "UV_PROJECT=" in audit_step["run"]
    assert "python -I -m agent" in audit_step["run"]
    assert "prepare_output_path" in audit_step["run"]
    assert "WRITE_BASELINE_PATH" in audit_step["run"]
    assert "generated-baseline.json" in audit_step["run"]
    assert "WRITE_BASELINE_BEFORE" in audit_step["run"]
    assert "st_mtime_ns" in audit_step["run"]
    assert "WRITE_BASELINE_AFTER" in audit_step["run"]
    assert "expand_argument_path" in audit_step["run"]
    assert "cannot share a symlink path" in audit_step["run"]
    assert "audit.sarif" in audit_step["run"]
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
    verify = workflow["jobs"]["verify-artifact"]
    assert verify["needs"] == "small-repo"
    verify_steps = verify["steps"]
    assert any(step.get("uses") == "actions/checkout@v4" for step in verify_steps)
    download_step = next(step for step in verify_steps if step.get("uses") == "actions/download-artifact@v4")
    assert download_step["with"] == {"name": "mumei-audit-evidence", "path": "evidence"}
    assert "if" not in download_step
    verify_step = next(step for step in verify_steps if step.get("name") == "Verify downloaded action evidence artifact")
    verify_text = verify_step["run"]
    assert "verify_audit_evidence_artifact.py evidence" in verify_text
    assert "--require-hidden-companion" in verify_text
    assert "--forbidden-literal fake-password-value" in verify_text
    assert "if" not in verify_step
    assert "--fail-on high-confidence" in audit_args
    assert action_step["with"]["migration-execution-output"] == ".mumei-audit/migration_execution.json"
    baseline = json.loads((ROOT / "examples" / "ci-small-repo" / "baseline.json").read_text(encoding="utf-8"))
    assert baseline == {"version": "mumei.audit-baseline/v1", "fingerprints": []}
    publish = next(step for step in steps if step.get("name") == "Publish measured action runtime")
    assert "setup_seconds" in publish["run"]
    assert "audit_seconds" in publish["run"]
    assert "total_seconds" in publish["run"]
    assert "migration_execution_status" in publish["run"]
    assert "migration_execution_ready_count" in publish["run"]
    assert "migration_execution_operational_error_count" in publish["run"]


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


def test_composite_action_fails_after_copying_candidate_operational_error(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "src").mkdir()
    state = tmp_path / "action-state"
    (state / "timing").mkdir(parents=True)
    output = tmp_path / "github-output"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        """#!/usr/bin/env python3
import json
import sys
from pathlib import Path

args = sys.argv[1:]
if args[:5] != ["run", "python", "-I", "-m", "agent"]:
    raise SystemExit(0)
rest = args[5:]
if "--help" in rest:
    print("--migration-execution-output")
    raise SystemExit(0)

def option(name):
    if name not in rest:
        return ""
    index = rest.index(name)
    return rest[index + 1] if index + 1 < len(rest) else ""

audit_output = Path(option("--output"))
sarif_output = Path(option("--sarif-output"))
migration_output = Path(option("--migration-execution-output"))
audit_output.write_text(json.dumps({"verification_status": "unverifiable", "finding_counts": {}}), encoding="utf-8")
sarif_output.write_text("{}", encoding="utf-8")
generated = migration_output.parent / f"{migration_output.stem}.migration-execution"
generated.mkdir(parents=True, exist_ok=True)
(generated / ".mumei-generated-artifacts").write_text("generated\\n", encoding="utf-8")
migration_output.write_text(
    json.dumps(
        {
            "schema": "mumei.migration-execution/v1",
            "generated_at": "2026-01-01T00:00:00Z",
            "source": {},
            "audit": {},
            "selection": {},
            "operational_errors": [],
            "candidates": [
                {
                    "execution_state": "operational_error",
                    "function_name": "f",
                    "source_provenance": {},
                    "selection": {},
                    "extracted_contract": {},
                    "generated_mm": {},
                    "heal": {},
                    "verification": {},
                    "unbound_audit_diagnostics": {},
                    "contract_provenance": {},
                    "evidence_blockers": [],
                    "operational_errors": ["verifier transport failed"],
                    "review_required": True,
                }
            ],
            "summary": {"ready_for_human_review": 0, "blocked": 0, "operational_error": 1, "candidate_count": 1, "review_required": True},
            "artifact_paths": {"migration_execution": str(migration_output), "generated_artifacts": str(generated)},
            "evidence_boundary": ["generated .mm only; not host semantic equivalence"],
        }
    ),
    encoding="utf-8",
)
raise SystemExit(0)
""",
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)

    audit_step = next(step for step in _action()["runs"]["steps"] if step["name"] == "Run mumei-agent audit")
    probe = tmp_path / "audit-step.sh"
    probe.write_text(audit_step["run"].replace("${{ github.action_path }}", str(ACTION_PATH.parent)), encoding="utf-8")
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "GITHUB_WORKSPACE": str(workspace),
        "ACTION_STATE": str(state),
        "AGENT_ROOT": str(ROOT),
        "GITHUB_OUTPUT": str(output),
        "CODE_FILE": "src",
        "LANGUAGE": "python",
        "AUDIT_ARGS": "",
        "AUDIT_OUTPUT": ".mumei-audit/audit.json",
        "SARIF_OUTPUT": ".mumei-audit/audit.sarif",
        "MIGRATION_EXECUTION_OUTPUT": ".mumei-audit/migration_execution.json",
    }

    completed = subprocess.run(["bash", "-e", "-o", "pipefail", str(probe)], cwd=workspace, env=env, capture_output=True, text=True)

    assert completed.returncode == 2
    assert "candidate operational_error" in completed.stdout
    assert (state / "migration-execution" / "migration_execution.json").is_file()
    assert (state / "migration-execution" / "generated-artifacts" / ".mumei-generated-artifacts").is_file()
    outputs = output.read_text(encoding="utf-8")
    assert "audit_exit_code=0" in outputs
    assert "migration_execution_status=emitted_by_audit_cli" in outputs
    assert "migration_execution_operational_error_count=1" in outputs


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


def test_migration_execution_action_contract_strings() -> None:
    action = _action()
    text = ACTION_PATH.read_text(encoding="utf-8")

    assert "migration-execution-output" in action["inputs"]
    assert "migration_execution_status" in action["outputs"]
    assert "migration_execution_ready_count" in action["outputs"]
    assert "migration_execution_operational_error_count" in action["outputs"]
    assert "--migration-execution-output" in text
    assert "ARGS+=(--auto-migrate)" in text
    assert "prepare_workspace_output_path.py" in text
    assert 'rm -f "$MIGRATION_JSON"' not in text
    assert 'migration execution output path already exists; choose a fresh output path' in text
    assert '--precheck-error "$MIGRATION_PRECHECK_ERROR"' in text
    assert "collect_migration_execution.py" in text
    assert "migration-execution/status.json" in text
    assert 'MIGRATION_COLLECTOR_EXIT" -eq 3' in text
    assert 'candidate operational_error' in text
    assert '--audit-json "$ACTION_STATE/audit.json"' in text
    assert 'sarif_file: ${{ env.ACTION_STATE }}/audit.sarif' in text


def test_prepare_workspace_output_path_contains_traversal(tmp_path: Path) -> None:
    helper = SUMMARY_SCRIPT.parent / "prepare_workspace_output_path.py"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    inside = subprocess.run(
        [sys.executable, str(helper), str(workspace), "evidence/migration.json"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert inside.stdout.strip() == str(workspace / "evidence" / "migration.json")
    outside = subprocess.run(
        [sys.executable, str(helper), str(workspace), "../migration.json"],
        capture_output=True,
        text=True,
    )
    assert outside.returncode != 0
    absolute_outside = subprocess.run(
        [sys.executable, str(helper), str(workspace), str(tmp_path / "migration.json")],
        capture_output=True,
        text=True,
    )
    assert absolute_outside.returncode != 0


def test_collect_migration_execution_copies_role_separated_evidence_and_redacts_secrets(tmp_path: Path) -> None:
    from agent.audit_models import AuditResult
    from agent.migration_execution import build_migration_execution

    class VerifyClient:
        def verify(self, source_path, report_dir=None, extra_args=None, spec_code_mapping=None, collect_decidable_metrics=False):
            if extra_args and "--output" in extra_args:
                Path(extra_args[extra_args.index("--output") + 1]).write_text('{"proof":"fake"}\n', encoding="utf-8")
            return {"success": True, "report": {"status": "success"}, "stdout": "{}", "stderr": ""}

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "payment.py"
    source.write_text("def withdraw():\n    pass\n", encoding="utf-8")
    secret = "fake-password-value"
    skeleton = (
        'atom withdraw() -> i64 {\n'
        '    requires: author == "editor" and password == "' + secret + '";\n'
        '    ensures: result >= 0;\n'
        '    body: { 0 }\n'
        '}'
    )
    result = AuditResult(
        success=False,
        source_file=str(source),
        language="python",
        spec_extracted=True,
        verification_status="unverifiable",
        migration_hints=[{"function_name": "withdraw", "priority": "high", "reason": "contract violation", "skeleton": skeleton, "next_step": "review"}],
        finding_counts={"code": 1, "spec": 0, "errors": 0},
    )
    migration_json = workspace / "migration_execution.json"
    build_migration_execution(result, output_path=migration_json, mumei_client=VerifyClient())
    state = tmp_path / "state"
    output = tmp_path / "outputs"

    completed = subprocess.run(
        [
            sys.executable,
            str(SUMMARY_SCRIPT.parent / "collect_migration_execution.py"),
            "--requested", "true",
            "--cli-supported", "true",
            "--migration-json", str(migration_json),
            "--workspace", str(workspace),
            "--state-dir", str(state),
            "--github-output", str(output),
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    copied = state / "migration-execution" / "migration_execution.json"
    assert copied.is_file()
    assert (state / "migration-execution" / "generated-artifacts").is_dir()
    artifact_text = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in (state / "migration-execution").rglob("*") if path.is_file())
    assert "editor" in artifact_text
    assert secret not in artifact_text
    status = json.loads((state / "migration-execution" / "status.json").read_text(encoding="utf-8"))
    assert status["status"] == "emitted_by_audit_cli"
    assert status["counts"]["blocked"] == 1
    output_text = output.read_text(encoding="utf-8")
    assert "migration_execution_status=emitted_by_audit_cli" in output_text
    assert "migration_execution_operational_error_count=0" in output_text


def test_collect_migration_execution_missing_or_escaping_artifact_is_operational_error(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state = tmp_path / "state"
    output = tmp_path / "outputs"
    helper = SUMMARY_SCRIPT.parent / "collect_migration_execution.py"
    missing = subprocess.run(
        [
            sys.executable,
            str(helper),
            "--requested", "true",
            "--cli-supported", "true",
            "--migration-json", str(workspace / "missing.json"),
            "--workspace", str(workspace),
            "--state-dir", str(state),
            "--github-output", str(output),
        ],
        capture_output=True,
        text=True,
    )
    assert missing.returncode == 2
    status = json.loads((state / "migration-execution" / "status.json").read_text(encoding="utf-8"))
    assert status["status"] == "operational_error"
    assert "migration_execution_status=operational_error" in output.read_text(encoding="utf-8")

    unsupported = subprocess.run(
        [
            sys.executable,
            str(helper),
            "--requested", "true",
            "--cli-supported", "false",
            "--migration-json", str(workspace / "missing.json"),
            "--workspace", str(workspace),
            "--state-dir", str(tmp_path / "state2"),
            "--github-output", str(tmp_path / "outputs2"),
        ],
        capture_output=True,
        text=True,
    )
    assert unsupported.returncode == 2


def test_summarize_audit_includes_migration_execution_counts_and_boundary(tmp_path: Path) -> None:
    audit_json = tmp_path / "audit.json"
    audit_json.write_text('{"verification_status":"unverifiable","finding_counts":{}}', encoding="utf-8")
    timing = tmp_path / "timing"
    timing.mkdir()
    migration = tmp_path / "migration-status.json"
    migration.write_text(
        json.dumps(
            {
                "status": "emitted_by_audit_cli",
                "counts": {"ready_for_human_review": 0, "blocked": 2, "operational_error": 1},
                "review_required": True,
                "boundary": "Generated .mm evidence only; not host-code semantic equivalence proof.",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "migration-auto-migrate").write_text("added\n", encoding="utf-8")
    summary = tmp_path / "summary.md"
    env = {**os.environ, "GITHUB_STEP_SUMMARY": str(summary)}

    subprocess.run(
        [
            sys.executable,
            str(SUMMARY_SCRIPT),
            "--audit-json", str(audit_json),
            "--exit-code", "1",
            "--timing-dir", str(timing),
            "--migration-status-json", str(migration),
        ],
        env=env,
        check=True,
    )

    text = summary.read_text(encoding="utf-8")
    assert "ready `0`, blocked `2`, operational_error `1`" in text
    assert "review_required `true`" in text
    assert "not host-code semantic equivalence proof" in text
    assert "failing the action because at least one candidate is `operational_error`" in text
    assert "`--auto-migrate` was added automatically" in text


def test_collect_migration_execution_rejects_malformed_and_escaping_generated_dir(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    helper = SUMMARY_SCRIPT.parent / "collect_migration_execution.py"

    def run(state: Path, migration_json: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(helper),
                "--requested", "true",
                "--cli-supported", "true",
                "--migration-json", str(migration_json),
                "--workspace", str(workspace),
                "--state-dir", str(state),
            ],
            capture_output=True,
            text=True,
        )

    malformed = workspace / "malformed.json"
    malformed.write_text("{not json", encoding="utf-8")
    assert run(tmp_path / "malformed-state", malformed).returncode == 2

    outside = tmp_path / "outside-generated"
    outside.mkdir()
    escaping = workspace / "escaping.json"
    escaping.write_text(
        json.dumps(
            {
                "schema": "mumei.migration-execution/v1",
                "generated_at": "2026-01-01T00:00:00Z",
                "source": {},
                "audit": {},
                "selection": {},
                "operational_errors": [],
                "candidates": [],
                "summary": {"ready_for_human_review": 0, "blocked": 0, "operational_error": 0, "candidate_count": 0, "review_required": False},
                "artifact_paths": {"migration_execution": str(escaping), "generated_artifacts": str(outside)},
                "evidence_boundary": ["generated .mm only"],
            }
        ),
        encoding="utf-8",
    )
    escaped = run(tmp_path / "escaping-state", escaping)
    assert escaped.returncode == 2
    status = json.loads((tmp_path / "escaping-state" / "migration-execution" / "status.json").read_text(encoding="utf-8"))
    assert "escapes the caller workspace" in status["error"]


def test_collect_migration_execution_rejects_inconsistent_summary(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    generated = workspace / "execution.migration-execution"
    generated.mkdir()
    migration_json = workspace / "execution.json"
    migration_json.write_text(
        json.dumps(
            {
                "schema": "mumei.migration-execution/v1",
                "generated_at": "2026-01-01T00:00:00Z",
                "source": {},
                "audit": {},
                "selection": {},
                "operational_errors": [],
                "candidates": [{
                    "execution_state": "blocked",
                    "function_name": "f",
                    "source_provenance": {},
                    "selection": {},
                    "extracted_contract": {},
                    "generated_mm": {},
                    "heal": {},
                    "verification": {},
                    "unbound_audit_diagnostics": {},
                    "contract_provenance": {},
                    "evidence_blockers": [],
                    "operational_errors": [],
                    "review_required": True,
                }],
                "summary": {"ready_for_human_review": 0, "blocked": 0, "operational_error": 0, "candidate_count": 1, "review_required": True},
                "artifact_paths": {"migration_execution": str(migration_json), "generated_artifacts": str(generated)},
                "evidence_boundary": ["generated .mm only"],
            }
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(SUMMARY_SCRIPT.parent / "collect_migration_execution.py"),
            "--requested", "true",
            "--cli-supported", "true",
            "--migration-json", str(migration_json),
            "--workspace", str(workspace),
            "--state-dir", str(tmp_path / "state"),
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2


def test_collect_migration_execution_candidate_operational_error_fails_after_copying(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    generated = workspace / "execution.migration-execution"
    generated.mkdir()
    (generated / ".mumei-generated-artifacts").write_text("generated\n", encoding="utf-8")
    migration_json = workspace / "execution.json"
    migration_json.write_text(
        json.dumps(
            {
                "schema": "mumei.migration-execution/v1",
                "generated_at": "2026-01-01T00:00:00Z",
                "source": {},
                "audit": {},
                "selection": {},
                "operational_errors": [],
                "candidates": [
                    {
                        "execution_state": "operational_error",
                        "function_name": "f",
                        "source_provenance": {},
                        "selection": {},
                        "extracted_contract": {},
                        "generated_mm": {},
                        "heal": {},
                        "verification": {},
                        "unbound_audit_diagnostics": {},
                        "contract_provenance": {},
                        "evidence_blockers": [],
                        "operational_errors": ["verifier transport failed"],
                        "review_required": True,
                    }
                ],
                "summary": {"ready_for_human_review": 0, "blocked": 0, "operational_error": 1, "candidate_count": 1, "review_required": True},
                "artifact_paths": {"migration_execution": str(migration_json), "generated_artifacts": str(generated)},
                "evidence_boundary": ["generated .mm only; not host semantic equivalence"],
            }
        ),
        encoding="utf-8",
    )
    state = tmp_path / "state"
    output = tmp_path / "outputs"
    completed = subprocess.run(
        [
            sys.executable,
            str(SUMMARY_SCRIPT.parent / "collect_migration_execution.py"),
            "--requested", "true",
            "--cli-supported", "true",
            "--migration-json", str(migration_json),
            "--workspace", str(workspace),
            "--state-dir", str(state),
            "--github-output", str(output),
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 3
    assert (state / "migration-execution" / "migration_execution.json").is_file()
    assert (state / "migration-execution" / "generated-artifacts" / ".mumei-generated-artifacts").is_file()
    status = json.loads((state / "migration-execution" / "status.json").read_text(encoding="utf-8"))
    assert status["status"] == "emitted_by_audit_cli"
    assert status["counts"]["operational_error"] == 1
    output_text = output.read_text(encoding="utf-8")
    assert "migration_execution_status=emitted_by_audit_cli" in output_text
    assert "migration_execution_operational_error_count=1" in output_text


def test_collect_migration_execution_precheck_error_is_machine_readable(tmp_path: Path) -> None:
    output = tmp_path / "outputs"
    state = tmp_path / "state"
    completed = subprocess.run(
        [
            sys.executable,
            str(SUMMARY_SCRIPT.parent / "collect_migration_execution.py"),
            "--requested", "true",
            "--cli-supported", "false",
            "--workspace", str(tmp_path),
            "--state-dir", str(state),
            "--github-output", str(output),
            "--precheck-error", "migration execution output path already exists; choose a fresh output path",
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    status = json.loads((state / "migration-execution" / "status.json").read_text(encoding="utf-8"))
    assert status["status"] == "operational_error"
    assert "already exists" in status["error"]
    assert "migration_execution_status=operational_error" in output.read_text(encoding="utf-8")


def test_collect_migration_execution_not_requested_has_machine_readable_default(tmp_path: Path) -> None:
    output = tmp_path / "outputs"
    completed = subprocess.run(
        [
            sys.executable,
            str(SUMMARY_SCRIPT.parent / "collect_migration_execution.py"),
            "--requested", "false",
            "--cli-supported", "false",
            "--workspace", str(tmp_path),
            "--state-dir", str(tmp_path / "state"),
            "--github-output", str(output),
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert output.read_text(encoding="utf-8") == "migration_execution_status=not_requested\nmigration_execution_ready_count=0\nmigration_execution_operational_error_count=0\n"
    assert not (tmp_path / "state" / "migration-execution").exists()


def _sha256_text(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_downloaded_action_artifact(root: Path, *, state: str = "blocked") -> None:
    root.mkdir(parents=True)
    (root / "audit.json").write_text(
        json.dumps({"verification_status": "unverifiable", "finding_counts": {}, "migration_hints": [], "trusted_atoms": []}),
        encoding="utf-8",
    )
    (root / "audit.sarif").write_text(json.dumps({"version": "2.1.0"}), encoding="utf-8")
    (root / "generated-baseline.json").write_text(
        json.dumps({"version": "mumei.audit-baseline/v1", "fingerprints": []}), encoding="utf-8"
    )
    (root / "audit.stdout.log").write_text("", encoding="utf-8")
    (root / "audit.stderr.log").write_text("audit diagnostics\n", encoding="utf-8")
    timing = root / "timing"
    timing.mkdir()
    for name, value in {"start": 100, "setup_end": 110, "audit_start": 111, "audit_end": 120}.items():
        (timing / name).write_text(f"{value}\n", encoding="utf-8")
    (root / "migration-auto-migrate").write_text("added\n", encoding="utf-8")

    migration_dir = root / "migration-execution"
    generated = migration_dir / "generated-artifacts"
    cache = generated / ".mumei" / "cache"
    cache.mkdir(parents=True)
    (generated / ".mumei-generated-artifacts").write_text("generated\n", encoding="utf-8")
    (cache / "verification_cache.json").write_text("{}\n", encoding="utf-8")
    mm_text = "atom divide() -> i64 { requires: divisor != 0; ensures: true; body: { 0 } }\n"
    proof_text = '{"proof": true}\n'
    sarif_text = '{"version": "2.1.0"}\n'
    (generated / "divide.mm").write_text(mm_text, encoding="utf-8")
    (generated / "divide.proof.json").write_text(proof_text, encoding="utf-8")
    (generated / "divide.sarif").write_text(sarif_text, encoding="utf-8")

    counts = {"ready_for_human_review": 0, "blocked": 0, "operational_error": 0}
    counts[state] = 1
    original_generated = "/original/workspace/.mumei-audit/migration_execution.migration-execution"
    boundary = "A verified generated .mm skeleton proves only the skeleton contract as written; it is not proof that host-language code implements the same behavior."
    execution = {
        "schema": "mumei.migration-execution/v1",
        "candidates": [
            {
                "execution_state": state,
                "generated_mm": {
                    "path": f"{original_generated}/divide.mm",
                    "sha256": _sha256_text(mm_text),
                },
                "verification": {
                    "proof_certificate": {
                        "written": True,
                        "path": f"{original_generated}/divide.proof.json",
                        "sha256": _sha256_text(proof_text),
                    },
                    "sarif": {
                        "written": True,
                        "path": f"{original_generated}/divide.sarif",
                        "sha256": _sha256_text(sarif_text),
                    },
                },
            }
        ],
        "summary": {**counts, "candidate_count": 1, "review_required": True},
        "artifact_paths": {
            "migration_execution": "/original/workspace/.mumei-audit/migration_execution.json",
            "generated_artifacts": original_generated,
        },
        "evidence_boundary": [boundary],
    }
    migration_dir.mkdir(exist_ok=True)
    (migration_dir / "migration_execution.json").write_text(json.dumps(execution), encoding="utf-8")
    status = {
        "status": "emitted_by_audit_cli",
        "ready_count": counts["ready_for_human_review"],
        "counts": counts,
        "review_required": True,
        "boundary": boundary,
        "generated_artifacts_copied": sum(1 for path in generated.rglob("*") if path.is_file()),
    }
    (migration_dir / "status.json").write_text(json.dumps(status), encoding="utf-8")


def _run_downloaded_artifact_verifier(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VERIFY_ARTIFACT_SCRIPT), str(root), *args],
        capture_output=True,
        text=True,
    )


def test_verify_downloaded_action_artifact_accepts_blocked_review_success_path(tmp_path: Path) -> None:
    artifact = tmp_path / "evidence"
    _write_downloaded_action_artifact(artifact)

    completed = _run_downloaded_artifact_verifier(artifact, "--require-hidden-companion", "--forbidden-literal", "fake-password-value")

    assert completed.returncode == 0, completed.stderr
    assert "generated companion files verified: 5" in completed.stdout
    assert "hidden generated companion files verified: 2" in completed.stdout
    assert "not host semantic-equivalence proof" in completed.stdout
    assert "baseline boundary: generated CI policy artifact; not evidence" in completed.stdout


def test_verify_downloaded_action_artifact_accepts_ready_review_success_path(tmp_path: Path) -> None:
    artifact = tmp_path / "evidence"
    _write_downloaded_action_artifact(artifact, state="ready_for_human_review")

    completed = _run_downloaded_artifact_verifier(artifact)

    assert completed.returncode == 0, completed.stderr
    assert "migration execution candidates verified: 1" in completed.stdout


def test_verify_downloaded_action_artifact_accepts_unwritten_proof_and_sarif_as_nonclaims(tmp_path: Path) -> None:
    artifact = tmp_path / "evidence"
    _write_downloaded_action_artifact(artifact)
    generated = artifact / "migration-execution" / "generated-artifacts"
    (generated / "divide.proof.json").unlink()
    (generated / "divide.sarif").unlink()
    execution_path = artifact / "migration-execution" / "migration_execution.json"
    execution = json.loads(execution_path.read_text(encoding="utf-8"))
    verification = execution["candidates"][0]["verification"]
    verification["proof_certificate"] = {
        "written": False,
        "path": verification["proof_certificate"]["path"],
        "sha256": None,
    }
    verification["sarif"] = {
        "written": False,
        "path": verification["sarif"]["path"],
        "sha256": None,
    }
    execution_path.write_text(json.dumps(execution), encoding="utf-8")
    status_path = artifact / "migration-execution" / "status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["generated_artifacts_copied"] = 3
    status_path.write_text(json.dumps(status), encoding="utf-8")

    completed = _run_downloaded_artifact_verifier(artifact)

    assert completed.returncode == 0, completed.stderr


def test_verify_downloaded_action_artifact_rejects_candidate_operational_error(tmp_path: Path) -> None:
    artifact = tmp_path / "evidence"
    _write_downloaded_action_artifact(artifact, state="operational_error")

    completed = _run_downloaded_artifact_verifier(artifact)

    assert completed.returncode != 0
    assert "candidate operational_error" in completed.stderr


def test_verify_downloaded_action_artifact_rejects_missing_timing(tmp_path: Path) -> None:
    artifact = tmp_path / "evidence"
    _write_downloaded_action_artifact(artifact)
    (artifact / "timing" / "audit_end").unlink()

    completed = _run_downloaded_artifact_verifier(artifact)

    assert completed.returncode != 0
    assert "timing" in completed.stderr


def test_verify_downloaded_action_artifact_rejects_missing_hidden_companion_when_required(tmp_path: Path) -> None:
    artifact = tmp_path / "evidence"
    _write_downloaded_action_artifact(artifact)
    generated = artifact / "migration-execution" / "generated-artifacts"
    (generated / ".mumei-generated-artifacts").unlink()
    status_path = artifact / "migration-execution" / "status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["generated_artifacts_copied"] = 4
    status_path.write_text(json.dumps(status), encoding="utf-8")

    completed = _run_downloaded_artifact_verifier(artifact, "--require-hidden-companion")

    assert completed.returncode != 0
    assert ".mumei-generated-artifacts" in completed.stderr


def test_verify_downloaded_action_artifact_accepts_fixture_without_hidden_companions(tmp_path: Path) -> None:
    artifact = tmp_path / "evidence"
    _write_downloaded_action_artifact(artifact)
    generated = artifact / "migration-execution" / "generated-artifacts"
    (generated / ".mumei-generated-artifacts").unlink()
    (generated / ".mumei" / "cache" / "verification_cache.json").unlink()
    status_path = artifact / "migration-execution" / "status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["generated_artifacts_copied"] = 3
    status_path.write_text(json.dumps(status), encoding="utf-8")

    completed = _run_downloaded_artifact_verifier(artifact)

    assert completed.returncode == 0, completed.stderr
    assert "hidden generated companion files verified: 0" in completed.stdout


def test_verify_downloaded_action_artifact_rejects_companion_count_mismatch(tmp_path: Path) -> None:
    artifact = tmp_path / "evidence"
    _write_downloaded_action_artifact(artifact)
    status_path = artifact / "migration-execution" / "status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["generated_artifacts_copied"] += 1
    status_path.write_text(json.dumps(status), encoding="utf-8")

    completed = _run_downloaded_artifact_verifier(artifact)

    assert completed.returncode != 0
    assert "file count changed" in completed.stderr


def test_verify_downloaded_action_artifact_rejects_generated_hash_mismatch(tmp_path: Path) -> None:
    artifact = tmp_path / "evidence"
    _write_downloaded_action_artifact(artifact)
    (artifact / "migration-execution" / "generated-artifacts" / "divide.mm").write_text("tampered\n", encoding="utf-8")

    completed = _run_downloaded_artifact_verifier(artifact)

    assert completed.returncode != 0
    assert "generated .mm sha256" in completed.stderr


def test_verify_downloaded_action_artifact_rejects_forbidden_literal(tmp_path: Path) -> None:
    artifact = tmp_path / "evidence"
    _write_downloaded_action_artifact(artifact)
    (artifact / "audit.stderr.log").write_text("fake-password-value\n", encoding="utf-8")

    completed = _run_downloaded_artifact_verifier(artifact, "--forbidden-literal", "fake-password-value")

    assert completed.returncode != 0
    assert "credential-like sentinel" in completed.stderr


def test_verify_downloaded_action_artifact_rejects_symlink_and_escaping_claim(tmp_path: Path) -> None:
    artifact = tmp_path / "evidence"
    _write_downloaded_action_artifact(artifact)
    generated = artifact / "migration-execution" / "generated-artifacts"
    victim = tmp_path / "victim"
    victim.write_text("victim\n", encoding="utf-8")
    (generated / "linked.mm").symlink_to(victim)

    completed = _run_downloaded_artifact_verifier(artifact)
    assert completed.returncode != 0
    assert "symlink" in completed.stderr

    (generated / "linked.mm").unlink()
    execution_path = artifact / "migration-execution" / "migration_execution.json"
    execution = json.loads(execution_path.read_text(encoding="utf-8"))
    execution["candidates"][0]["generated_mm"]["path"] = "/original/workspace/outside.mm"
    execution_path.write_text(json.dumps(execution), encoding="utf-8")
    completed = _run_downloaded_artifact_verifier(artifact)
    assert completed.returncode != 0
    assert "outside the generated artifact directory" in completed.stderr
