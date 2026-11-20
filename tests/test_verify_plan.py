import json
import subprocess
import sys
from pathlib import Path

import pytest

from agent.verify_schedule import build_plan_parser, main_plan, run_plan

PY = sys.executable
REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILE = "mumei.test/v1"
SECRET = "FAKE_SECRET_SENTINEL_VALUE_9f2c1d"


def manifest(adapter_id, **overrides):
    doc = {
        "schema_version": "mumei.verifier-adapter/v1",
        "adapter_id": adapter_id,
        "adapter_version": "1.0.0",
        "profiles": [PROFILE],
        "methods": ["deductive_proof"],
        "result_contracts": [
            {
                "profile": PROFILE,
                "method": "deductive_proof",
                "scope": "unbounded",
                "correspondence_relation": "exact_model",
                "correspondence_status": "assumed",
            }
        ],
        "input_formats": ["mumei.source-text/v1"],
        "required_permissions": [],
    }
    doc.update(overrides)
    return doc


@pytest.fixture
def inputs(tmp_path):
    def write(name, doc):
        path = tmp_path / f"FAKE_PRIVATE_{name}.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        return str(path)

    request = write(
        "request",
        {
            "profile": PROFILE,
            "method": "deductive_proof",
            "result_contract": {
                "profile": PROFILE,
                "method": "deductive_proof",
                "scope": "unbounded",
                "correspondence_relation": "exact_model",
                "correspondence_status": "assumed",
            },
            "input_format": "mumei.source-text/v1",
        },
    )
    policy = write(
        "policy",
        {"allowed_permissions": ["process.spawn"], "timeout_ms": 10_000},
    )
    observations = write(
        "observations",
        [
            {"adapter_id": "alpha", "availability": "available", "tool_version": "1.0.0", "stamp": 1},
            {"adapter_id": "beta", "availability": "available", "tool_version": "1.0.0", "stamp": 2},
        ],
    )
    adapters = write("adapters", [manifest("alpha"), manifest("beta", priority=5)])
    return {
        "request": request,
        "policy": policy,
        "observations": observations,
        "adapters": adapters,
    }


def args_for(inputs, **over):
    args = build_plan_parser().parse_args(
        [
            "--request", inputs["request"],
            "--adapters", inputs["adapters"],
            "--policy", inputs["policy"],
            "--observations", inputs["observations"],
        ]
    )
    for key, value in over.items():
        setattr(args, key, value)
    return args


def decisions(doc):
    return {d["adapter_id"]: list(d["reasons"]) for d in doc["decisions"]}


def cli(inputs, *extra, env_secret=False):
    env = {"PYTHONPATH": str(REPO_ROOT), "PATH": "/usr/bin:/bin"}
    if env_secret:
        env["MUMEI_TEST_SECRET"] = SECRET
    return subprocess.run(
        [
            PY, "-m", "agent", "verify-plan",
            "--request", inputs["request"],
            "--adapters", inputs["adapters"],
            "--policy", inputs["policy"],
            "--observations", inputs["observations"],
            *extra,
        ],
        capture_output=True, text=True, cwd=REPO_ROOT, env=env,
    )


def test_priority_selection_with_reasons(inputs):
    doc = run_plan(args_for(inputs))
    assert doc["schema_version"] == "mumei.verification-plan/v1"
    assert doc["selected"]["adapter_id"] == "beta"
    assert doc["fallback_from"] is None
    reasons = decisions(doc)
    assert reasons["beta"] == ["selected_priority"]
    assert reasons["alpha"] == ["compatible_not_selected"]


def test_explicit_selection_marks_selected_explicit(inputs, tmp_path):
    policy = tmp_path / "explicit.json"
    policy.write_text(json.dumps(
        {"allowed_permissions": ["process.spawn"],
         "selected_adapter": "alpha", "timeout_ms": 10_000}
    ))
    doc = run_plan(args_for(inputs, policy=str(policy)))
    assert doc["selected"]["adapter_id"] == "alpha"
    reasons = decisions(doc)
    assert reasons["alpha"] == ["selected_explicit"]
    assert doc["fallback_from"] is None


def test_fallback_from_records_denied_choice(inputs, tmp_path):
    policy = tmp_path / "denied.json"
    policy.write_text(json.dumps(
        {"allowed_permissions": ["process.spawn"],
         "selected_adapter": "alpha", "allow_fallback": True,
         "disabled_adapters": ["alpha"], "timeout_ms": 10_000}
    ))
    doc = run_plan(args_for(inputs, policy=str(policy)))
    assert doc["selected"]["adapter_id"] == "beta"
    assert doc["fallback_from"] == "alpha"
    reasons = decisions(doc)
    assert "disabled" in reasons["alpha"]
    assert reasons["beta"] == ["selected_fallback"]


def test_denied_fallback_selects_nothing(inputs, tmp_path):
    policy = tmp_path / "denied.json"
    policy.write_text(json.dumps(
        {"allowed_permissions": ["process.spawn"],
         "selected_adapter": "alpha", "disabled_adapters": ["alpha"],
         "timeout_ms": 10_000}
    ))
    doc = run_plan(args_for(inputs, policy=str(policy)))
    assert doc["selected"] is None
    reasons = decisions(doc)
    assert "disabled" in reasons["alpha"]
    assert reasons["beta"] == ["explicit_selection_blocks_automatic_route"]


def test_exclusion_reasons_are_exposed(inputs, tmp_path):
    policy = tmp_path / "pins.json"
    policy.write_text(json.dumps(
        {"allowed_permissions": ["process.spawn"],
         "tool_version_pins": [["alpha", "9.9.9"]],
         "timeout_ms": 10_000}
    ))
    obs = tmp_path / "obs.json"
    obs.write_text(json.dumps([
        {"adapter_id": "alpha", "availability": "available",
         "tool_version": "1.0.0", "stamp": 1},
        {"adapter_id": "beta", "availability": "missing", "stamp": 2},
    ]))
    doc = run_plan(args_for(inputs, policy=str(policy), observations=str(obs)))
    reasons = decisions(doc)
    assert "tool_version_mismatch" in reasons["alpha"]
    assert "tool_missing" in reasons["beta"]
    assert doc["selected"] is None


def test_unregistered_explicit_selection_is_named(inputs, tmp_path):
    policy = tmp_path / "ghost.json"
    policy.write_text(json.dumps(
        {"allowed_permissions": ["process.spawn"],
         "selected_adapter": "ghost", "timeout_ms": 10_000}
    ))
    doc = run_plan(args_for(inputs, policy=str(policy)))
    assert doc["selected"] is None
    reasons = decisions(doc)
    assert reasons["ghost"] == ["not_registered"]


def test_effective_nonsecret_settings_are_exposed(inputs):
    doc = run_plan(args_for(inputs))
    selected = doc["selected"]
    assert selected["timeout_ms"] <= 10_000
    assert selected["location"] == "local"
    assert "tool_version" in selected or "observed_tool_version" in selected


def test_closed_shape_rejects_unknown_policy_keys(inputs, tmp_path):
    policy = tmp_path / "bad.json"
    policy.write_text('{"allowed_permissions": [], "mystery_knob": 1}')
    out = subprocess.run(
        [
            PY, "-m", "agent", "verify-plan",
            "--request", inputs["request"],
            "--adapters", inputs["adapters"],
            "--policy", str(policy),
        ],
        capture_output=True, text=True, cwd=REPO_ROOT,
        env={"PYTHONPATH": str(REPO_ROOT), "PATH": "/usr/bin:/bin"},
    )
    assert out.returncode == 1
    assert out.stderr.startswith("verify-plan:")
    # Declared paths are redacted out of the failure text.
    assert str(policy) not in out.stderr


def test_output_file_written_and_input_overwrite_refused(inputs, tmp_path):
    out_path = tmp_path / "plan.json"
    out = cli(inputs, "--output", str(out_path))
    assert out.returncode == 0, out.stderr
    doc = json.loads(out_path.read_text(encoding="utf-8"))
    assert doc["schema_version"] == "mumei.verification-plan/v1"
    refused = cli(inputs, "--output", inputs["policy"])
    assert refused.returncode == 1
    assert refused.stderr.startswith("verify-plan:")


def test_no_secret_in_document_or_stderr(inputs, tmp_path):
    out_path = tmp_path / "plan.json"
    out = cli(inputs, "--output", str(out_path), env_secret=True)
    assert out.returncode == 0, out.stderr
    written = out_path.read_text(encoding="utf-8")
    assert SECRET not in written
    assert SECRET not in out.stdout
    assert SECRET not in out.stderr


def test_duplicate_observation_is_a_static_error(inputs, tmp_path):
    obs = tmp_path / "dup.json"
    obs.write_text(json.dumps([
        {"adapter_id": "alpha", "availability": "available", "stamp": 1},
        {"adapter_id": "alpha", "availability": "missing", "stamp": 2},
    ]))
    out = subprocess.run(
        [
            PY, "-m", "agent", "verify-plan",
            "--request", inputs["request"],
            "--adapters", inputs["adapters"],
            "--policy", inputs["policy"],
            "--observations", str(obs),
        ],
        capture_output=True, text=True, cwd=REPO_ROOT,
        env={"PYTHONPATH": str(REPO_ROOT), "PATH": "/usr/bin:/bin"},
    )
    assert out.returncode == 1
    assert out.stderr.startswith("verify-plan:")


def test_cli_doc_matches_library_doc(inputs):
    out = cli(inputs)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == json.loads(
        json.dumps(run_plan(args_for(inputs)))
    )
