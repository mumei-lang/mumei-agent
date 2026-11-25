import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent.plan_history_log import read_plan_history
from agent.verify_schedule import build_plan_parser, run_plan

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
        check=False, capture_output=True, text=True, cwd=REPO_ROOT, env=env,
    )


def write_overlay(tmp_path, name, manifests):
    path = tmp_path / name
    path.write_text(json.dumps(manifests), encoding="utf-8")
    return path


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


def _setting_inputs(inputs, tmp_path):
    adapters = tmp_path / "configured-adapters.json"
    adapters.write_text(json.dumps([
        manifest(
            "alpha",
            setting_specs=[
                {"name": "cache", "kind": "boolean", "default": False},
                {"name": "rounds", "kind": "integer", "default": 3, "minimum": 1, "maximum": 10},
                {"name": "strategy", "kind": "choice", "default": "balanced", "choices": ["balanced", "eager"]},
            ],
        ),
        manifest("beta", priority=5),
    ]), encoding="utf-8")
    return str(adapters)


def test_policy_adapter_settings_override_declared_defaults(inputs, tmp_path):
    adapters = _setting_inputs(inputs, tmp_path)
    policy = tmp_path / "configured-policy.json"
    policy.write_text(json.dumps({
        "allowed_permissions": ["process.spawn"],
        "selected_adapter": "alpha",
        "adapter_settings": [["alpha", [["rounds", 7], ["cache", True], ["strategy", "eager"]]]],
        "timeout_ms": 10_000,
    }), encoding="utf-8")

    doc = run_plan(args_for(inputs, adapters=adapters, policy=str(policy)))

    assert doc["selected"]["adapter_id"] == "alpha"
    assert doc["selected"]["adapter_settings"] == {
        "cache": True,
        "rounds": 7,
        "strategy": "eager",
    }
    assert "adapter_settings" not in doc["policy"]


@pytest.mark.parametrize(
    "settings",
    [
        None,
        {},
        [[]],
        [["alpha"]],
        [["alpha", {}]],
        [["alpha", [["rounds"]]]],
        [["alpha", [["rounds", 1, 2]]]],
    ],
)
def test_malformed_adapter_settings_declaration_is_rejected(inputs, tmp_path, settings):
    policy = tmp_path / "bad-settings.json"
    policy.write_text(json.dumps({
        "allowed_permissions": ["process.spawn"],
        "adapter_settings": settings,
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid adapter settings declaration"):
        run_plan(args_for(inputs, policy=str(policy)))


@pytest.mark.parametrize(
    "override,error",
    [
        ([["alpha", [["rounds", 0]]]], "setting value outside declared schema"),
        ([["alpha", [["unknown", 1]]]], "setting has no registered schema"),
        ([["ghost", []]], "settings have no registered adapter"),
        ([["alpha", [["cache", True], ["cache", False]]]], "duplicate adapter setting name"),
        ([["alpha", []], ["alpha", []]], "duplicate adapter settings"),
        ([["alpha", [["api_key", SECRET]]]], "setting channel is not permitted"),
    ],
)
def test_invalid_adapter_setting_never_becomes_a_route(inputs, tmp_path, override, error):
    adapters = _setting_inputs(inputs, tmp_path)
    policy = tmp_path / "invalid-settings.json"
    policy.write_text(json.dumps({
        "allowed_permissions": ["process.spawn"],
        "selected_adapter": "alpha",
        "allow_fallback": True,
        "adapter_settings": override,
        "timeout_ms": 10_000,
    }), encoding="utf-8")

    with pytest.raises(ValueError, match=error) as failure:
        run_plan(args_for(inputs, adapters=adapters, policy=str(policy)))
    assert SECRET not in str(failure.value)


def test_sensitive_setting_rejection_does_not_print_secret(inputs, tmp_path):
    adapters = _setting_inputs(inputs, tmp_path)
    policy = tmp_path / "sensitive-settings.json"
    policy.write_text(json.dumps({
        "allowed_permissions": ["process.spawn"],
        "adapter_settings": [["alpha", [["api_key", SECRET]]]],
    }), encoding="utf-8")
    output = tmp_path / "plan.json"

    out = subprocess.run(
        [
            PY, "-m", "agent", "verify-plan",
            "--request", inputs["request"],
            "--adapters", adapters,
            "--policy", str(policy),
            "--output", str(output),
        ],
        check=False, capture_output=True, text=True, cwd=REPO_ROOT,
        env={"PYTHONPATH": str(REPO_ROOT), "PATH": "/usr/bin:/bin"},
    )

    assert out.returncode == 1
    assert "setting channel is not permitted" in out.stderr
    assert SECRET not in out.stdout
    assert SECRET not in out.stderr
    assert not output.exists()


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
        check=False, capture_output=True, text=True, cwd=REPO_ROOT,
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


def test_output_hard_link_to_request_is_refused(inputs, tmp_path):
    request = Path(inputs["request"])
    original = request.read_bytes()
    output = tmp_path / "request-link.json"
    os.link(request, output)

    refused = cli(inputs, "--output", str(output))

    assert refused.returncode == 1
    assert "--output must not overwrite a declared input" in refused.stderr
    assert request.read_bytes() == original
    assert output.read_bytes() == original


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
        check=False, capture_output=True, text=True, cwd=REPO_ROOT,
        env={"PYTHONPATH": str(REPO_ROOT), "PATH": "/usr/bin:/bin"},
    )
    assert out.returncode == 1
    assert out.stderr.startswith("verify-plan:")


def test_cli_doc_matches_library_doc(inputs):
    out = cli(inputs)
    assert out.returncode == 0, out.stderr
    expected = json.dumps(
        run_plan(args_for(inputs)), indent=2, sort_keys=True
    ) + "\n"
    assert out.stdout == expected


def test_adapter_overlay_adds_a_higher_priority_adapter(inputs, tmp_path):
    observations = json.loads(
        Path(inputs["observations"]).read_text(encoding="utf-8")
    )
    observations.append(
        {
            "adapter_id": "gamma",
            "availability": "available",
            "tool_version": "1.0.0",
            "stamp": 3,
        }
    )
    observations_path = tmp_path / "observations-with-gamma.json"
    observations_path.write_text(json.dumps(observations), encoding="utf-8")
    overlay = write_overlay(
        tmp_path, "gamma-overlay.json", [manifest("gamma", priority=20)]
    )

    out = cli(
        {**inputs, "observations": str(observations_path)},
        "--adapter-overlay",
        str(overlay),
    )

    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout)["selected"]["adapter_id"] == "gamma"


def test_adapter_overlay_replaces_a_base_adapter(inputs, tmp_path):
    overlay = write_overlay(
        tmp_path,
        "replacement.json",
        [manifest("alpha", adapter_version="2.0.0", priority=10)],
    )

    out = cli(inputs, "--adapter-overlay", str(overlay))

    assert out.returncode == 0, out.stderr
    selected = json.loads(out.stdout)["selected"]
    assert selected["adapter_id"] == "alpha"
    assert selected["adapter_version"] == "2.0.0"


def test_later_adapter_overlay_replaces_earlier_overlay(inputs, tmp_path):
    first = write_overlay(
        tmp_path,
        "first-overlay.json",
        [manifest("alpha", adapter_version="2.0.0", priority=10)],
    )
    second = write_overlay(
        tmp_path,
        "second-overlay.json",
        [manifest("alpha", adapter_version="3.0.0", priority=20)],
    )

    out = cli(
        inputs,
        "--adapter-overlay",
        str(first),
        "--adapter-overlay",
        str(second),
    )

    assert out.returncode == 0, out.stderr
    selected = json.loads(out.stdout)["selected"]
    assert selected["adapter_id"] == "alpha"
    assert selected["adapter_version"] == "3.0.0"


def test_duplicate_adapter_ids_in_one_overlay_are_rejected(inputs, tmp_path):
    overlay = write_overlay(
        tmp_path,
        "duplicate-overlay.json",
        [
            manifest("gamma"),
            manifest("gamma", adapter_version="2.0.0"),
        ],
    )

    out = cli(inputs, "--adapter-overlay", str(overlay))

    assert out.returncode == 1
    assert "adapter overlay declares a duplicate adapter_id" in out.stderr
    assert str(tmp_path) not in out.stderr


@pytest.mark.parametrize("document", [[], {}])
def test_empty_or_non_array_adapter_overlay_is_rejected(
    inputs, tmp_path, document
):
    overlay = write_overlay(tmp_path, "invalid-overlay.json", document)

    out = cli(inputs, "--adapter-overlay", str(overlay))

    assert out.returncode == 1
    assert (
        "adapter overlay manifests must be a nonempty JSON array"
        in out.stderr
    )
    assert str(tmp_path) not in out.stderr


def test_adapter_overlay_paths_are_protected_from_outputs(inputs, tmp_path):
    overlay = write_overlay(
        tmp_path, "protected-overlay.json", [manifest("gamma")]
    )
    original = overlay.read_bytes()

    output_refused = cli(
        inputs,
        "--adapter-overlay",
        str(overlay),
        "--output",
        str(overlay),
    )
    history_refused = cli(
        inputs,
        "--adapter-overlay",
        str(overlay),
        "--history-log",
        str(overlay),
    )

    assert output_refused.returncode == 1
    assert "--output must not overwrite a declared input" in output_refused.stderr
    assert history_refused.returncode == 1
    assert (
        "--history-log must not overwrite a declared input or output"
        in history_refused.stderr
    )
    assert overlay.read_bytes() == original
    assert str(tmp_path) not in output_refused.stderr
    assert str(tmp_path) not in history_refused.stderr


def test_history_log_appends_emitted_plans_and_accepts_previous_head(inputs, tmp_path):
    history = tmp_path / "plan-history.jsonl"
    plain = cli(inputs)
    first = cli(inputs, "--history-log", str(history))

    assert plain.returncode == first.returncode == 0
    assert first.stdout == plain.stdout
    first_document = json.loads(first.stdout)
    first_entry = json.loads(history.read_text(encoding="utf-8").splitlines()[-1])
    first_head = first_entry["digest"]
    assert first.stderr == f"verify-plan: history head {first_head}\n"
    assert read_plan_history(str(history), expected_head=first_head) == (
        first_document,
    )

    second = cli(
        inputs,
        "--history-log",
        str(history),
        "--expected-history-head",
        first_head,
    )

    assert second.returncode == 0, second.stderr
    assert second.stdout == plain.stdout
    second_document = json.loads(second.stdout)
    second_entry = json.loads(history.read_text(encoding="utf-8").splitlines()[-1])
    second_head = second_entry["digest"]
    assert second.stderr == f"verify-plan: history head {second_head}\n"
    assert read_plan_history(str(history), expected_head=second_head) == (
        first_document,
        second_document,
    )


def test_stale_history_head_fails_before_writing_output(inputs, tmp_path):
    history = tmp_path / "plan-history.jsonl"
    first = cli(inputs, "--history-log", str(history))
    stale_head = json.loads(history.read_text(encoding="utf-8").splitlines()[-1])[
        "digest"
    ]
    cli(inputs, "--history-log", str(history))
    original = history.read_bytes()
    output = tmp_path / "must-not-exist.json"

    refused = cli(
        inputs,
        "--history-log",
        str(history),
        "--expected-history-head",
        stale_head,
        "--output",
        str(output),
    )

    assert first.returncode == 0
    assert refused.returncode == 1
    assert refused.stdout == ""
    assert history.read_bytes() == original
    assert not output.exists()
    assert str(tmp_path) not in refused.stderr


def test_expected_history_head_requires_history_log(inputs, tmp_path):
    refused = cli(inputs, "--expected-history-head", "0" * 64)

    assert refused.returncode == 1
    assert refused.stdout == ""
    assert str(tmp_path) not in refused.stderr


def test_history_log_cannot_overwrite_request_or_output(inputs, tmp_path):
    request = Path(inputs["request"])
    original_request = request.read_bytes()
    request_collision = cli(inputs, "--history-log", str(request))

    output = tmp_path / "plan.json"
    output_collision = cli(
        inputs, "--history-log", str(output), "--output", str(output)
    )

    assert request_collision.returncode == 1
    assert request.read_bytes() == original_request
    assert output_collision.returncode == 1
    assert request.read_bytes() == original_request
    assert not output.exists()
    assert str(tmp_path) not in request_collision.stderr
    assert str(tmp_path) not in output_collision.stderr


def test_history_log_hard_link_as_output_is_refused(inputs, tmp_path):
    history = tmp_path / "history.jsonl"
    first = cli(inputs, "--history-log", str(history))
    assert first.returncode == 0, first.stderr
    original = history.read_bytes()
    output = tmp_path / "out.json"
    os.link(history, output)

    refused = cli(
        inputs,
        "--history-log",
        str(history),
        "--output",
        str(output),
    )

    assert refused.returncode == 1
    assert (
        "--history-log must not overwrite a declared input or output"
        in refused.stderr
    )
    assert history.read_bytes() == original
    assert output.read_bytes() == original
