import hashlib
import json
import subprocess
import sys

import pytest

from agent.verify_schedule import (
    build_schedule_parser,
    main_schedule,
    run_schedule,
)

PY = sys.executable
SOURCE = b"FAKE_PRIVATE_SOURCE_NOT_EVIDENCE"
PROFILE = "mumei.test/v1"


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

    source = tmp_path / "FAKE_PRIVATE_SOURCE.mm"
    source.write_bytes(SOURCE)
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
        "policy", {"allowed_permissions": ["filesystem.read", "process.spawn"], "timeout_ms": 10_000}
    )
    observations = write(
        "observations",
        [
            {"adapter_id": "alpha", "availability": "available", "tool_version": "1.0.0", "stamp": 1},
            {"adapter_id": "beta", "availability": "available", "tool_version": "1.0.0", "stamp": 2},
        ],
    )
    adapters = write("adapters", [manifest("alpha"), manifest("beta")])
    argv_map = write(
        "argv",
        {
            "alpha": [PY, "-c", "import sys; sys.exit(3)"],
            "beta": [PY, "-c", "import sys; sys.exit(0)"],
        },
    )
    return {
        "request": request,
        "policy": policy,
        "observations": observations,
        "adapters": adapters,
        "argv_map": argv_map,
        "source": str(source),
    }


def args_for(inputs, **overrides):
    argv = [
        "--request", inputs["request"],
        "--adapters", inputs["adapters"],
        "--argv-map", inputs["argv_map"],
        "--policy", inputs["policy"],
        "--observations", inputs["observations"],
        "--source", inputs["source"],
    ]
    for key, value in overrides.items():
        argv += [f"--{key.replace('_', '-')}", str(value)]
    return build_schedule_parser().parse_args(argv)


def test_schedule_runs_fallback_and_emits_descriptor(inputs, capsys):
    args = args_for(inputs)
    assert main_schedule(args) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["schema_version"] == "mumei.attempt-schedule/v1"
    assert doc["outcome"] == "selected"
    assert doc["selected_adapter_id"] == "beta"
    assert [a["adapter_id"] for a in doc["attempts"]] == ["alpha", "beta"]
    assert "FAKE_PRIVATE" not in capsys.readouterr().out + repr(doc)
    assert SOURCE.decode() not in json.dumps(doc)


def test_output_writes_document(inputs, capsys, tmp_path):
    out = tmp_path / "schedule.json"
    args = args_for(inputs, output=str(out))
    assert main_schedule(args) == 0
    doc = json.loads(out.read_text())
    assert doc["outcome"] == "selected"
    assert capsys.readouterr().out == ""


def test_exhausted_and_not_schedulable(inputs, capsys):
    argv_map_fail = json.loads(open(inputs["argv_map"]).read())
    argv_map_fail["beta"] = [PY, "-c", "import sys; sys.exit(2)"]
    fail_path = inputs["argv_map"].replace("argv", "argvfail")
    with open(fail_path, "w") as f:
        json.dump(argv_map_fail, f)
    args = args_for({**inputs, "argv_map": fail_path})
    assert main_schedule(args) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["outcome"] == "exhausted"
    # No observations → nothing is eligible.
    argv = [
        "--request", inputs["request"],
        "--adapters", inputs["adapters"],
        "--argv-map", fail_path,
        "--policy", inputs["policy"],
        "--source", inputs["source"],
    ]
    args = build_schedule_parser().parse_args(argv)
    assert main_schedule(args) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["outcome"] == "not_schedulable"


def test_static_input_rejections(inputs, tmp_path, capsys):
    def bad_file(name, doc):
        path = tmp_path / f"FAKE_PRIVATE_BAD_{name}.json"
        path.write_text(doc if isinstance(doc, str) else json.dumps(doc))
        return str(path)

    cases = [
        # request: unknown key, missing contract, non-source format
        bad_file("req1", {"profile": PROFILE, "method": "deductive_proof", "bogus": 1}),
        bad_file("req2", {"profile": PROFILE, "method": "deductive_proof"}),
        bad_file("req3", {"profile": PROFILE, "method": "deductive_proof",
                          "result_contract": {"profile": PROFILE, "method": "deductive_proof",
                                              "scope": "unbounded", "correspondence_relation": "exact_model",
                                              "correspondence_status": "assumed"},
                          "input_format": "mumei.other/v1"}),
    ]
    for request in cases:
        args = args_for({**inputs, "request": request})
        with pytest.raises(SystemExit):
            main_schedule(args)
        assert capsys.readouterr().out == ""

    for name, doc in [
        ("pol1", {"allowed_permissions": [], "unknown": 1}),
        ("pol2", {"timeout_ms": "soon"}),
        ("obs1", [{"adapter_id": "a", "extra": 1}]),
        ("argv1", {"alpha": []}),
        ("argv2", {"alpha": ["ok", 1]}),
        ("adp1", [{"adapter_id": "x"}]),
        ("raw", "not json"),
    ]:
        if name.startswith("pol"):
            args = args_for({**inputs, "policy": bad_file(name, doc)})
        elif name.startswith("obs"):
            args = args_for({**inputs, "observations": bad_file(name, doc)})
        elif name.startswith("argv"):
            args = args_for({**inputs, "argv_map": bad_file(name, doc)})
        elif name == "adp1":
            args = args_for({**inputs, "adapters": bad_file(name, doc)})
        else:
            args = args_for({**inputs, "policy": bad_file(name, doc)})
        with pytest.raises(SystemExit):
            main_schedule(args)
        err = capsys.readouterr().err
        assert err.startswith("verify-schedule:")
        assert "FAKE_PRIVATE" not in err


def test_missing_files_fail_statically(inputs, capsys):
    for key in ("request", "adapters", "argv_map", "policy", "observations", "source"):
        args = args_for({**inputs, key: "/nonexistent-declared-path"})
        with pytest.raises(SystemExit):
            main_schedule(args)
        assert "FAKE_PRIVATE" not in capsys.readouterr().err
        assert "/nonexistent" not in capsys.readouterr().err


def test_undeclared_argv_adapter_is_not_dispatched(inputs, capsys, tmp_path):
    argv_map = {"beta": [PY, "-c", "import sys; sys.exit(0)"]}
    path = tmp_path / "argv_partial.json"
    path.write_text(json.dumps(argv_map))
    args = args_for({**inputs, "argv_map": str(path)})
    assert main_schedule(args) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["outcome"] == "selected"
    assert doc["attempts"][0]["terminal_state"] == "not_dispatched"
    assert doc["attempts"][0]["adapter_id"] == "alpha"


def test_cli_subcommand_dispatches(tmp_path):
    source = tmp_path / "src.mm"
    source.write_bytes(SOURCE)
    files = {
        "request": {"profile": PROFILE, "method": "deductive_proof",
                    "result_contract": {"profile": PROFILE, "method": "deductive_proof",
                                        "scope": "unbounded", "correspondence_relation": "exact_model",
                                        "correspondence_status": "assumed"},
                    "input_format": "mumei.source-text/v1"},
        "policy": {"allowed_permissions": []},
        "adapters": [manifest("alpha")],
        "argv": {"alpha": [PY, "-c", "import sys; sys.exit(0)"]},
        "obs": [{"adapter_id": "alpha", "availability": "available", "tool_version": "1.0.0"}],
    }
    paths = {}
    for name, doc in files.items():
        p = tmp_path / f"{name}.json"
        p.write_text(json.dumps(doc))
        paths[name] = str(p)
    out = subprocess.run(
        [PY, "-m", "agent", "verify-schedule",
         "--request", paths["request"], "--adapters", paths["adapters"],
         "--argv-map", paths["argv"], "--policy", paths["policy"],
         "--observations", paths["obs"], "--source", str(source)],
        capture_output=True, text=True, cwd="/home/ubuntu/repos/mumei-agent",
        env={"PYTHONPATH": "/home/ubuntu/repos/mumei-agent", "PATH": "/usr/bin:/bin"},
    )
    assert out.returncode == 0, out.stderr
    doc = json.loads(out.stdout)
    assert doc["schema_version"] == "mumei.attempt-schedule/v1"
    assert doc["outcome"] == "selected"
    assert "FAKE_PRIVATE" not in out.stdout + out.stderr
