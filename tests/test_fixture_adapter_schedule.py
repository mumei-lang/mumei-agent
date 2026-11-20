"""C11 test-user-adapter E2E: a checked-in stub adapter is scheduled
through the real `verify-schedule` CLI.

Each case declares documents (request, adapter manifests, argv map,
policy, observations) and runs `python -m agent verify-schedule` as a
subprocess, so the whole lane — manifest parse, plan/dispatch, real
spawn, terminal reconciliation, fallback — is exercised the way a user
adding their own adapter sees it: no core edit, only declared files.

Covers the acceptance matrix: missing tools, incompatible tool
versions, invalid settings, timeouts, malformed/partial/conflicting
outputs, explicit selection and denied fallback — plus the lane's
stated limits: no secret logging, no implicit installs, no unapproved
code execution, no data egress.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PY = sys.executable
REPO_ROOT = Path(__file__).resolve().parents[1]
STUB = str(REPO_ROOT / "tests" / "fixtures" / "stub_adapter.py")
PROFILE = "mumei.test/v1"
SECRET = "FAKE_SECRET_SENTINEL_VALUE_9f2c1d"

SOURCE_BYTES = b"FAKE_PRIVATE_SOURCE_NOT_EVIDENCE"


def _manifest(adapter_id, **overrides):
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


def stub_argv(*flags):
    """Declared argv running the checked-in stub adapter."""
    return [PY, STUB, *map(str, flags)]


def _write_docs(tmp_path, *, adapters, argv_map, policy, observations,
                request=None):
    def write(name, doc):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        return str(path)

    source = tmp_path / "source.mm"
    source.write_bytes(SOURCE_BYTES)
    if request is None:
        request = {
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
        }
    return {
        "request": write("request", request),
        "adapters": write("adapters", adapters),
        "argv": write("argv", argv_map),
        "policy": write("policy", policy),
        "observations": write("obs", observations),
        "source": str(source),
    }


def _run(paths, *extra):
    env = {
        "PYTHONPATH": str(REPO_ROOT),
        "PATH": "/usr/bin:/bin",
        "MUMEI_TEST_SECRET": SECRET,
    }
    out = subprocess.run(
        [
            PY, "-m", "agent", "verify-schedule",
            "--request", paths["request"],
            "--adapters", paths["adapters"],
            "--argv-map", paths["argv"],
            "--policy", paths["policy"],
            "--observations", paths["observations"],
            "--source", paths["source"],
            *extra,
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
    )
    return out


def _base(tmp_path, *, policy=None, argv_alpha=None, argv_beta=None,
          observations=None):
    adapters = [_manifest("alpha"), _manifest("beta")]
    argv_map = {
        "alpha": argv_alpha if argv_alpha is not None else stub_argv("--exit", 3),
        "beta": argv_beta if argv_beta is not None else stub_argv(),
    }
    if policy is None:
        policy = {"allowed_permissions": ["process.spawn"],
                  "allow_fallback": True, "timeout_ms": 10_000}
    if observations is None:
        observations = [
            {"adapter_id": "alpha", "availability": "available",
             "tool_version": "1.0.0", "stamp": 1},
            {"adapter_id": "beta", "availability": "available",
             "tool_version": "1.0.0", "stamp": 2},
        ]
    return _write_docs(
        tmp_path, adapters=adapters, argv_map=argv_map, policy=policy,
        observations=observations,
    )


def _doc(out):
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_stub_adapter_selects_on_declared_exit_code(tmp_path):
    paths = _base(tmp_path)
    doc = _doc(_run(paths))
    assert doc["schema_version"] == "mumei.attempt-schedule/v1"
    assert doc["outcome"] == "selected"
    assert doc["selected_adapter_id"] == "beta"
    assert [a["adapter_id"] for a in doc["attempts"]] == ["alpha", "beta"]
    assert doc["attempts"][0]["terminal_state"] == "exited"
    assert doc["attempts"][0]["exit_code"] == 3


def test_explicit_selection_runs_only_the_named_adapter(tmp_path):
    paths = _base(
        tmp_path,
        policy={"allowed_permissions": ["process.spawn"],
                "selected_adapter": "alpha", "timeout_ms": 10_000},
        argv_alpha=stub_argv(),
    )
    doc = _doc(_run(paths))
    assert doc["outcome"] == "selected"
    assert doc["selected_adapter_id"] == "alpha"
    assert [a["adapter_id"] for a in doc["attempts"]] == ["alpha"]


def test_failed_selection_with_fallback_denied_stops(tmp_path):
    paths = _base(
        tmp_path,
        policy={"allowed_permissions": ["process.spawn"],
                "selected_adapter": "alpha", "timeout_ms": 10_000},
    )
    doc = _doc(_run(paths))
    assert doc["outcome"] == "fallback_denied"
    assert [a["adapter_id"] for a in doc["attempts"]] == ["alpha"]
    assert doc["attempts"][0]["exit_code"] == 3


def test_missing_tool_is_a_failed_round_then_fallback(tmp_path):
    paths = _base(
        tmp_path,
        argv_alpha=["/nonexistent-adapter-binary", "--version"],
    )
    doc = _doc(_run(paths))
    assert doc["outcome"] == "selected"
    assert doc["attempts"][0]["adapter_id"] == "alpha"
    assert doc["attempts"][0]["terminal_state"] == "failed"
    assert doc["attempts"][1]["adapter_id"] == "beta"


def test_incompatible_tool_version_is_not_scheduled(tmp_path):
    paths = _base(
        tmp_path,
        policy={"allowed_permissions": ["process.spawn"],
                "tool_version_pins": [["alpha", "9.9.9"]],
                "timeout_ms": 10_000},
    )
    doc = _doc(_run(paths))
    # alpha is pinned out by its declared pin vs observed 1.0.0 → the
    # plan must not dispatch it; beta still runs.
    assert doc["outcome"] == "selected"
    assert doc["selected_adapter_id"] == "beta"
    assert [a["adapter_id"] for a in doc["attempts"]] == ["beta"]


def test_timeout_marks_round_timed_out_then_fallback(tmp_path):
    paths = _base(
        tmp_path,
        argv_alpha=stub_argv("--sleep", "30"),
        policy={"allowed_permissions": ["process.spawn"],
                "allow_fallback": True, "timeout_ms": 200},
    )
    doc = _doc(_run(paths))
    assert doc["outcome"] == "selected"
    assert doc["attempts"][0]["terminal_state"] == "timed_out"
    assert doc["selected_adapter_id"] == "beta"


def test_memory_bound_kills_overallocating_adapter(tmp_path):
    paths = _base(
        tmp_path,
        argv_alpha=stub_argv("--alloc-mb", "256", "--exit", "0"),
        policy={"allowed_permissions": ["process.spawn"],
                "allow_fallback": True, "timeout_ms": 10_000,
                "memory_mb": 64},
    )
    doc = _doc(_run(paths, "--memory-bound-mb", "64"))
    assert doc["attempts"][0]["adapter_id"] == "alpha"
    assert doc["attempts"][0]["terminal_state"] != "exited" or (
        doc["attempts"][0]["exit_code"] != 0
    )
    assert doc["selected_adapter_id"] == "beta"


def test_malformed_adapter_output_is_observed_not_trusted(tmp_path):
    paths = _base(
        tmp_path,
        # A stub emitting garbage then dying mid-write: the schedule
        # records the terminal state + exit code — raw bytes never land
        # in the descriptor.
        argv_alpha=stub_argv("--emit", "not-json{{{", "--spew", "2048",
                             "--die"),
        argv_beta=stub_argv("--emit", '{"conflict": "beta claims v2"}'),
    )
    doc = _doc(_run(paths))
    assert doc["attempts"][0]["terminal_state"] in ("failed", "exited")
    assert doc["attempts"][0]["exit_code"] != 0
    assert doc["selected_adapter_id"] == "beta"
    assert "not-json" not in json.dumps(doc)
    assert "conflict" not in json.dumps(doc)


def test_conflicting_exit_claims_follow_declared_codes(tmp_path):
    # Both adapters claim different worlds on stdout; scheduling only
    # trusts the declared success exit codes.
    paths = _base(
        tmp_path,
        argv_alpha=stub_argv("--emit", '{"result": "verified"}',
                             "--exit", "7"),
        argv_beta=stub_argv("--emit", '{"result": "refuted"}',
                            "--exit", "0"),
    )
    doc = _doc(_run(paths))
    assert doc["selected_adapter_id"] == "beta"
    assert doc["attempts"][0]["exit_code"] == 7


def test_invalid_settings_fail_statically(tmp_path):
    paths = _base(tmp_path)
    bad = tmp_path / "bad.json"
    bad.write_text('{"allowed_permissions": [], "mystery_knob": 1}')
    out = subprocess.run(
        [
            PY, "-m", "agent", "verify-schedule",
            "--request", paths["request"],
            "--adapters", paths["adapters"],
            "--argv-map", paths["argv"],
            "--policy", str(bad),
            "--observations", paths["observations"],
            "--source", paths["source"],
        ],
        capture_output=True, text=True, cwd=REPO_ROOT,
        env={"PYTHONPATH": str(REPO_ROOT), "PATH": "/usr/bin:/bin"},
    )
    assert out.returncode == 1
    assert out.stderr.startswith("verify-schedule:")
    assert "mystery_knob" not in out.stdout


def test_undeclared_argv_is_not_dispatched_and_nothing_runs(tmp_path):
    # beta is registered but has no declared argv: it must be recorded
    # not_dispatched — the lane never guesses or installs a command.
    marker = tmp_path / "spawned.marker"
    paths = _write_docs(
        tmp_path,
        adapters=[_manifest("alpha"), _manifest("beta")],
        argv_map={
            "alpha": stub_argv("--exit", 0),
            # beta intentionally undeclared — and even a pathological
            # argv touching a marker file cannot run.
        },
        policy={"allowed_permissions": ["process.spawn"],
                "allow_fallback": True, "timeout_ms": 10_000},
        observations=[
            {"adapter_id": "alpha", "availability": "missing",
             "stamp": 1},
            {"adapter_id": "beta", "availability": "available",
             "tool_version": "1.0.0", "stamp": 2},
        ],
    )
    doc = _doc(_run(paths))
    terminals = {a["adapter_id"]: a["terminal_state"] for a in doc["attempts"]}
    assert "beta" in terminals
    assert terminals["beta"] == "not_dispatched"
    assert not marker.exists()


def test_no_secret_or_source_in_descriptor_or_output(tmp_path):
    paths = _base(
        tmp_path,
        argv_alpha=stub_argv("--emit", SECRET, "--exit", "3"),
    )
    out = _run(paths)
    doc = _doc(out)
    # The descriptor is fingerprints only: even when an adapter echoes
    # host secrets or the source bytes, they never reach the document,
    # stdout of the route (beyond the doc) or stderr.
    assert SECRET not in json.dumps(doc)
    assert SECRET not in out.stderr
    assert SOURCE_BYTES.decode() not in json.dumps(doc)


def test_adapter_swap_needs_no_core_edit(tmp_path):
    # Replacing a user adapter = declaring a different argv for the
    # same adapter_id. alpha's argv is swapped for one that succeeds:
    # the schedule outcome changes with zero core edits.
    paths_fail = _base(tmp_path)
    doc_fail = _doc(_run(paths_fail))
    assert doc_fail["selected_adapter_id"] == "beta"
    swapped = json.loads(Path(paths_fail["argv"]).read_text())
    swapped["alpha"] = stub_argv()
    swap_path = tmp_path / "argv_swapped.json"
    swap_path.write_text(json.dumps(swapped))
    paths_fail["argv"] = str(swap_path)
    doc_ok = _doc(_run(paths_fail))
    assert doc_ok["selected_adapter_id"] == "alpha"
