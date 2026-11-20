import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent.verify_schedule import (
    build_schedule_parser,
    main_schedule,
    run_schedule,
)

PY = sys.executable
REPO_ROOT = Path(__file__).resolve().parents[1]
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
        capture_output=True, text=True, cwd=REPO_ROOT,
        env={"PYTHONPATH": str(REPO_ROOT), "PATH": "/usr/bin:/bin"},
    )
    assert out.returncode == 0, out.stderr
    doc = json.loads(out.stdout)
    assert doc["schema_version"] == "mumei.attempt-schedule/v1"
    assert doc["outcome"] == "selected"
    assert "FAKE_PRIVATE" not in out.stdout + out.stderr


def test_output_must_not_overwrite_declared_input(inputs, capsys):
    args = args_for(inputs, output=inputs["source"])
    with pytest.raises(SystemExit):
        main_schedule(args)
    err = capsys.readouterr().err
    assert err.startswith("verify-schedule:")
    assert "FAKE_PRIVATE" not in err
    # The source survives untouched.
    assert open(inputs["source"], "rb").read() == SOURCE


def test_output_must_not_overwrite_declared_input_hardlink(
    inputs, capsys, tmp_path
):
    # A hardlink is a different path onto the same inode.
    hard = tmp_path / "policy_hardlink.json"
    os.link(inputs["policy"], hard)
    args = args_for(inputs, output=str(hard))
    with pytest.raises(SystemExit):
        main_schedule(args)
    assert "must not overwrite" in capsys.readouterr().err


def test_policy_requires_explicit_allowed_permissions(inputs, tmp_path, capsys):
    policy = tmp_path / "FAKE_PRIVATE_policy.json"
    policy.write_text(json.dumps({"timeout_ms": 10_000}))
    args = args_for({**inputs, "policy": str(policy)})
    with pytest.raises(SystemExit):
        main_schedule(args)
    assert capsys.readouterr().err.startswith("verify-schedule:")


def test_empty_allowed_locations_is_rejected(inputs, capsys):
    policy = json.loads(open(inputs["policy"]).read())
    policy["allowed_locations"] = []
    path = inputs["policy"].replace("policy", "polnoloc")
    with open(path, "w") as f:
        json.dump(policy, f)
    args = args_for({**inputs, "policy": path})
    with pytest.raises(SystemExit):
        main_schedule(args)
    assert capsys.readouterr().err.startswith("verify-schedule:")


def test_schedule_falls_back_to_manifest_attempt_argv(tmp_path, capsys):
    # With ``allow_manifest_attempt_argv`` the adapter's declared
    # command runs when the host argv_map has no entry for it.
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
        "policy",
        {
            "allowed_permissions": ["filesystem.read", "process.spawn"],
            "timeout_ms": 10_000,
            "selected_adapter": "alpha",
            "allow_manifest_attempt_argv": True,
        },
    )
    observations = write(
        "observations",
        [
            {
                "adapter_id": "alpha",
                "availability": "available",
                "tool_version": "1.0.0",
                "stamp": 1,
            },
        ],
    )
    adapters = write(
        "adapters",
        [
            manifest(
                "alpha",
                attempt_argv=[PY, "-c", "import sys; sys.exit(0)"],
            )
        ],
    )
    argv_map = write("argv", {})
    argv = [
        "--request", request,
        "--adapters", adapters,
        "--argv-map", argv_map,
        "--policy", policy,
        "--observations", observations,
        "--source", str(source),
    ]
    args = build_schedule_parser().parse_args(argv)
    result = run_schedule(args)
    attempts = result["attempts"]
    assert attempts and attempts[0]["terminal_state"] == "exited"
    assert attempts[0]["exit_code"] == 0


def test_manifest_attempt_argv_rejects_non_list(tmp_path):
    from agent.verification_planner import AdapterDescriptor

    with pytest.raises(ValueError):
        AdapterDescriptor.from_manifest(
            manifest("alpha", attempt_argv="not-a-list")
        )


def test_manifest_attempt_argv_needs_policy_optin(tmp_path):
    # Without ``allow_manifest_attempt_argv`` a manifest-declared
    # command stays inert — the attempt is not dispatched.
    import json as _json

    def write(name, doc):
        path = tmp_path / f"FAKE_PRIVATE_{name}.json"
        path.write_text(_json.dumps(doc), encoding="utf-8")
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
        "policy",
        {
            "allowed_permissions": ["filesystem.read", "process.spawn"],
            "timeout_ms": 10_000,
            "selected_adapter": "alpha",
        },
    )
    observations = write(
        "observations",
        [
            {
                "adapter_id": "alpha",
                "availability": "available",
                "tool_version": "1.0.0",
                "stamp": 1,
            },
        ],
    )
    adapters = write(
        "adapters",
        [manifest("alpha", attempt_argv=[PY, "-c", "import sys; sys.exit(0)"])],
    )
    argv_map = write("argv", {})
    argv = [
        "--request", request,
        "--adapters", adapters,
        "--argv-map", argv_map,
        "--policy", policy,
        "--observations", observations,
        "--source", str(source),
    ]
    args = build_schedule_parser().parse_args(argv)
    result = run_schedule(args)
    assert result["attempts"][0]["terminal_state"] == "not_dispatched"


def _stdin_case(tmp_path, opt_in):
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
    policy_doc = {
        "allowed_permissions": ["filesystem.read", "process.spawn"],
        "timeout_ms": 10_000,
        "selected_adapter": "alpha",
        # The command itself is also manifest-declared, so argv opt-in is
        # needed either way; stdin opt-in stays the variable under test.
        "allow_manifest_attempt_argv": True,
    }
    if opt_in:
        policy_doc["allow_manifest_attempt_stdin"] = True
    policy = write("policy", policy_doc)
    observations = write(
        "observations",
        [
            {
                "adapter_id": "alpha",
                "availability": "available",
                "tool_version": "1.0.0",
                "stamp": 1,
            },
        ],
    )
    probe = (
        "import sys;"
        "sys.exit(0 if sys.stdin.buffer.read() == b'FEED' else 3)"
    )
    adapters = write(
        "adapters",
        [
            manifest(
                "alpha",
                attempt_argv=[PY, "-c", probe],
                attempt_stdin="FEED",
            )
        ],
    )
    argv_map = write("argv", {})
    argv = [
        "--request", request,
        "--adapters", adapters,
        "--argv-map", argv_map,
        "--policy", policy,
        "--observations", observations,
        "--source", str(source),
    ]
    return build_schedule_parser().parse_args(argv)


def test_manifest_attempt_stdin_feeds_attempt_with_optin(tmp_path):
    # With ``allow_manifest_attempt_stdin`` the declared text is piped to
    # the attempt process (the probe exits 0 only on b"FEED").
    args = _stdin_case(tmp_path, True)
    result = run_schedule(args)
    assert result["attempts"][0]["terminal_state"] == "exited"
    assert result["attempts"][0]["exit_code"] == 0
    assert result["outcome"] == "selected"


def test_manifest_attempt_stdin_needs_policy_optin(tmp_path):
    # Without the opt-in the declared stdin stays inert — the probe
    # reads EOF, exits 3 and the schedule is not selected.
    args = _stdin_case(tmp_path, False)
    result = run_schedule(args)
    assert result["attempts"][0]["exit_code"] == 3
    assert result["outcome"] != "selected"


def test_manifest_attempt_stdin_rejects_non_string():
    from agent.verification_planner import AdapterDescriptor

    for bad in (["x"], 7, {"v": 1}):
        with pytest.raises(ValueError):
            AdapterDescriptor.from_manifest(
                manifest("alpha", attempt_stdin=bad)
            )


def test_core_flag_records_evidence_acceptance(inputs, capsys, tmp_path):
    # Stub Core emitting the v1 representation diagnostic for `evidence
    # check`; the selected attempt's captured output is fed to it.
    diagnostic = {
        "schema_version": "mumei.evidence-representation-check/v1",
        "evidence_schema_version": "mumei.verification-evidence/v1",
        "representation": "valid",
        "acceptance": "not_evaluated",
        "checks_not_performed": [
            "claim_truth", "file_identity", "freshness",
            "producer_authenticity", "semantic_correspondence",
            "artifact_semantics",
        ],
    }
    core = tmp_path / "mumei-stub"
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "evidence" ] && [ "$2" = "check" ]; then\n'
        "    cat > /dev/null\n"
        "    printf %s '" + json.dumps(diagnostic) + "'\n"
        "    exit 0\n"
        "fi\n"
        "exit 2\n"
    )
    core.chmod(0o755)
    args = args_for(inputs, core=str(core))
    assert main_schedule(args) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["evidence_check"]["outcome"] == "valid"
    assert doc["evidence_acceptance"]["accepted"] is True


def test_core_flag_requires_absolute_existing_path(inputs):
    args = args_for(inputs, core="relative/mumei")
    with pytest.raises(ValueError):
        run_schedule(args)


def _requirement(tmp_path):
    req = tmp_path / "requirement.json"
    req.write_text(
        json.dumps({"schema_version": "mumei.evidence-requirement/v1"}),
        encoding="utf-8",
    )
    return req


def _accept_core(tmp_path, verdict):
    # Stub Core `evidence accept`: binds the descriptor's evidence
    # fingerprint to the stdin bytes it was fed, then emits the verdict
    # with its matching exit code (accepted→0, rejected→1).
    code = 0 if verdict == "accepted" else 1 if verdict == "rejected" else 3
    core = tmp_path / f"mumei-stub-accept-{verdict}"
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "evidence" ] && [ "$2" = "accept" ]; then\n'
        '    [ "$5" = "--requirement" ] || exit 4\n'
        '    [ -f "$6" ] || exit 5\n'
        "    sum=$(sha256sum | cut -d' ' -f1)\n"
        "    req=$(sha256sum \"$6\" | cut -d' ' -f1)\n"
        '    printf %s "{\\"schema_version\\":\\"mumei.evidence-acceptance/v1\\",'
        '\\"requirement_fingerprint\\":\\"$req\\",'
        '\\"evidence_fingerprint\\":\\"$sum\\",'
        '\\"acceptance\\":\\"evaluated\\",'
        '\\"verdict\\":\\"' + verdict + '\\"}"\n'
        f"    exit {code}\n"
        "fi\n"
        "exit 2\n"
    )
    core.chmod(0o755)
    return core


@pytest.mark.parametrize("verdict,accepted", [
    ("accepted", True), ("rejected", False), ("inconclusive", False),
])
def test_core_requirement_records_the_core_verdict(
    inputs, capsys, tmp_path, verdict, accepted
):
    req = _requirement(tmp_path)
    core = _accept_core(tmp_path, verdict)
    args = args_for(
        inputs, core=str(core), core_requirement=str(req)
    )
    assert main_schedule(args) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["evidence_check"]["outcome"] == verdict
    assert doc["evidence_acceptance"]["accepted"] is accepted
    assert doc["evidence_acceptance"]["requirement_fingerprint"] == (
        hashlib.sha256(req.read_bytes()).hexdigest()
    )


def test_core_requirement_failed_check_records_failed(
    inputs, capsys, tmp_path
):
    req = _requirement(tmp_path)
    core = tmp_path / "mumei-stub-accept-bad"
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "evidence" ] && [ "$2" = "accept" ]; then\n'
        "    cat > /dev/null\n"
        "    printf %s 'not-a-descriptor'\n"
        "    exit 0\n"
        "fi\n"
        "exit 2\n"
    )
    core.chmod(0o755)
    args = args_for(
        inputs, core=str(core), core_requirement=str(req)
    )
    assert main_schedule(args) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["evidence_check"]["outcome"] == "failed"
    assert doc["evidence_acceptance"]["accepted"] is False


def test_core_requirement_needs_core(inputs):
    req_args = args_for(inputs, core_requirement="/tmp/req.json")
    with pytest.raises(ValueError, match="--core-requirement"):
        run_schedule(req_args)


def test_core_requirement_needs_absolute_existing_path(inputs, tmp_path):
    core = _accept_core(tmp_path, "accepted")
    for bad in ("relative/req.json", str(tmp_path / "missing.json")):
        args = args_for(
            inputs, core=str(core), core_requirement=bad
        )
        with pytest.raises(ValueError, match="--core-requirement"):
            run_schedule(args)


def test_output_must_not_overwrite_the_requirement(inputs, tmp_path):
    req = _requirement(tmp_path)
    core = _accept_core(tmp_path, "accepted")
    # --output hardlinks the declared requirement — same inode through a
    # different name must still trip the overwrite guard.
    out = tmp_path / "req.json"
    os.link(req, out)
    args = args_for(
        inputs,
        core=str(core),
        core_requirement=str(req),
        output=str(out),
    )
    with pytest.raises(SystemExit):
        main_schedule(args)


def _requirement_list(tmp_path):
    doc = tmp_path / "requirement-list.json"
    doc.write_text(
        json.dumps({
            "schema_version": "mumei.evidence-requirement-list/v1",
            "requirements": [{"schema_version": "mumei.evidence-requirement/v1"}],
        }),
        encoding="utf-8",
    )
    return doc


def _accept_list_core(tmp_path, verdict):
    # Stub Core `evidence accept --requirement-list`: binds the evidence
    # fingerprint to the stdin bytes and the requirement-list fingerprint
    # to the declared file, then emits the conjunctive descriptor.
    code = 0 if verdict == "accepted" else 1 if verdict == "rejected" else 3
    core = tmp_path / f"mumei-stub-accept-list-{verdict}"
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "evidence" ] && [ "$2" = "accept" ]; then\n'
        '    [ "$5" = "--requirement-list" ] || exit 4\n'
        '    [ -f "$6" ] || exit 5\n'
        "    sum=$(sha256sum | cut -d' ' -f1)\n"
        '    req=$(sha256sum "$6" | cut -d\' \' -f1)\n'
        '    printf %s "{\\"schema_version\\":\\"mumei.evidence-requirement-list-acceptance/v1\\",'
        '\\"requirement_schema_version\\":\\"mumei.evidence-requirement-list/v1\\",'
        '\\"evidence_schema_version\\":\\"mumei.verification-evidence/v1\\",'
        '\\"requirement_list_fingerprint\\":\\"$req\\",'
        '\\"evidence_fingerprint\\":\\"$sum\\",'
        '\\"acceptance\\":\\"evaluated\\",'
        '\\"verdict\\":\\"' + verdict + '\\"}"\n'
        f"    exit {code}\n"
        "fi\n"
        "exit 2\n"
    )
    core.chmod(0o755)
    return core


@pytest.mark.parametrize("verdict,accepted", [
    ("accepted", True), ("rejected", False), ("inconclusive", False),
])
def test_core_requirement_list_records_the_core_verdict(
    inputs, capsys, tmp_path, verdict, accepted
):
    req = _requirement_list(tmp_path)
    core = _accept_list_core(tmp_path, verdict)
    args = args_for(
        inputs, core=str(core), core_requirement_list=str(req)
    )
    assert main_schedule(args) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["evidence_check"]["outcome"] == verdict
    assert doc["evidence_acceptance"]["accepted"] is accepted
    assert doc["evidence_acceptance"]["requirement_fingerprint"] == (
        hashlib.sha256(req.read_bytes()).hexdigest()
    )


def test_export_evidence_acceptance_writes_the_promotable_triple(
    inputs, capsys, tmp_path
):
    req = _requirement_list(tmp_path)
    core = _accept_list_core(tmp_path, "accepted")
    export = tmp_path / "promotable"
    args = args_for(
        inputs,
        core=str(core),
        core_requirement_list=str(req),
        export_evidence_acceptance=str(export),
    )
    assert main_schedule(args) == 0
    assert json.loads(capsys.readouterr().out)["evidence_check"]["outcome"] == "accepted"
    requirement_list = (export / "requirement-list.json").read_bytes()
    evidence = (export / "evidence.json").read_bytes()
    acceptance = json.loads((export / "acceptance.json").read_text())
    assert requirement_list == req.read_bytes()
    assert acceptance["schema_version"] == (
        "mumei.evidence-requirement-list-acceptance/v1"
    )
    assert acceptance["requirement_list_fingerprint"] == (
        hashlib.sha256(requirement_list).hexdigest()
    )
    assert acceptance["evidence_fingerprint"] == (
        hashlib.sha256(evidence).hexdigest()
    )


def test_export_evidence_acceptance_skips_a_failed_check(
    inputs, capsys, tmp_path
):
    req = _requirement_list(tmp_path)
    core = tmp_path / "mumei-stub-accept-list-bad"
    core.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "evidence" ] && [ "$2" = "accept" ]; then\n'
        "    cat > /dev/null\n"
        "    printf %s 'not-a-descriptor'\n"
        "    exit 0\n"
        "fi\n"
        "exit 2\n"
    )
    core.chmod(0o755)
    export = tmp_path / "promotable"
    args = args_for(
        inputs,
        core=str(core),
        core_requirement_list=str(req),
        export_evidence_acceptance=str(export),
    )
    assert main_schedule(args) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["evidence_check"]["outcome"] == "failed"
    assert not export.exists()


def test_core_requirement_list_flag_contract(inputs, tmp_path):
    core = _accept_list_core(tmp_path, "accepted")
    req = _requirement_list(tmp_path)
    single = _requirement(tmp_path)
    # Conflicts with --core-requirement.
    with pytest.raises(ValueError, match="--core-requirement-list"):
        run_schedule(args_for(
            inputs,
            core=str(core),
            core_requirement=str(single),
            core_requirement_list=str(req),
        ))
    # Requires --core.
    with pytest.raises(ValueError, match="--core-requirement-list"):
        run_schedule(args_for(inputs, core_requirement_list=str(req)))
    # Needs an absolute existing path.
    for bad in ("relative/req.json", str(tmp_path / "missing.json")):
        with pytest.raises(ValueError, match="--core-requirement-list"):
            run_schedule(args_for(
                inputs, core=str(core), core_requirement_list=bad
            ))


def test_export_evidence_acceptance_flag_contract(inputs, tmp_path):
    core = _accept_list_core(tmp_path, "accepted")
    req = _requirement_list(tmp_path)
    export = tmp_path / "promotable"
    # Requires --core-requirement-list.
    with pytest.raises(ValueError, match="--export-evidence-acceptance"):
        run_schedule(args_for(
            inputs,
            core=str(core),
            export_evidence_acceptance=str(export),
        ))
    # Requires an absolute path.
    with pytest.raises(ValueError, match="--export-evidence-acceptance"):
        run_schedule(args_for(
            inputs,
            core=str(core),
            core_requirement_list=str(req),
            export_evidence_acceptance="relative/export",
        ))
