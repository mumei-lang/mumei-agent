"""Route tests for `python -m agent go-summaries`.

A stub helper stands in for a provisioned go-types binary: the route is
tested against the same declared-report contract the real helper speaks,
never against a live compiler.
"""
import hashlib
import json
import stat
from pathlib import Path

import pytest

from agent.go_summaries import build_parser, main
from agent.go_type_snapshot import PACKAGE_PROFILE, TARGETS
from tests.test_go_type_snapshot import SOURCE, schema_fixture


def _write_helper(tmp_path: Path, payload: bytes | None, *, fail: str = "") -> Path:
    helper = tmp_path / "go-types-stub"
    if fail == "exit":
        body = "echo 'broken' >&2; exit 3"
    elif fail == "stderr":
        body = "echo 'noise' >&2; cat >/dev/null; echo '{}'"
    else:
        report = tmp_path / "report.json"
        report.write_bytes(payload)
        body = f"cat >/dev/null; cat {report}"
    helper.write_text(f"#!/bin/sh\n{body}\n")
    helper.chmod(helper.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return helper


def _write_source(tmp_path: Path, name: str, source: str) -> Path:
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return path


def _args(helper: Path, *sources: Path, extra=()) -> list[str]:
    args = ["--go-types", str(helper)]
    for source in sources:
        args += ["--source", str(source)]
    return args + list(extra)


def _run(capsys, argv: list[str]):
    try:
        code = main(build_parser().parse_args(argv))
    except SystemExit as exc:
        code = exc.code
    out = capsys.readouterr()
    return code, out.out, out.err


def _package_fixture(files: dict[str, str]) -> dict:
    scalar = {
        "kind": "integer",
        "basic_name": "int64",
        "bit_width": 64,
        "signed": True,
        "type_id": "",
    }
    fntype = {
        "kind": "function",
        "basic_name": "",
        "bit_width": 0,
        "signed": None,
        "type_id": "",
    }
    digests = {
        name: hashlib.sha256(src.encode()).hexdigest()
        for name, src in files.items()
    }
    h = hashlib.sha256()
    for name, digest in digests.items():
        h.update(name.encode())
        h.update(b"\x00")
        h.update(bytes.fromhex(digest))
    bindings, functions = [], []
    for index, (name, src) in enumerate(files.items()):
        raw = src.encode()
        fn = f"F{index}"
        start = src.index(fn)
        binding_id = f"sha256:{digests[name]}:{index}:{start}:0:{len(raw)}"
        bindings.append(
            {
                "id": binding_id,
                "name": fn,
                "kind": "function",
                "span": {"file": index, "start": start, "end": start + 2},
                "scope": {"file": index, "start": 0, "end": len(raw)},
                "type": fntype,
            }
        )
        functions.append(
            {
                "binding_id": binding_id,
                "body": {
                    "file": index,
                    "start": src.index("{") + 1,
                    "end": src.index("}"),
                },
                "parameters": [],
                "results": [{"binding_id": "", "type": scalar}],
                "method": False,
                "generic": False,
                "variadic": False,
            }
        )
    return {
        "profile": PACKAGE_PROFILE,
        "source_sha256": h.hexdigest(),
        "files": [
            {"name": name, "sha256": digest} for name, digest in digests.items()
        ],
        "target_arch": "amd64",
        "language_version": "go1.23",
        "compiler_version": "go1.27.1",
        "status": "ok",
        "bindings": bindings,
        "references": [],
        "functions": functions,
        "calls": [],
        "gaps": [],
    }


def test_single_file_route_emits_a_restorable_manifest(tmp_path, capsys):
    helper = _write_helper(tmp_path, json.dumps(schema_fixture()).encode())
    source = _write_source(tmp_path, "main.go", SOURCE)
    code, out, err = _run(
        capsys, _args(helper, source, extra=["--target-arch", "amd64"])
    )
    assert code == 0 and err == ""
    manifest = json.loads(out)
    assert manifest["schema_version"] == "mumei.go-scalar-parameter-deps/v1"
    assert len(manifest["functions"]) == 1
    from agent.go_interprocedural import GoSummarySet

    restored = GoSummarySet.from_dict(manifest)
    assert restored.to_dict() == manifest


def test_multi_file_route_uses_the_package_profile(tmp_path, capsys):
    files = {
        "a.go": "package p\nfunc F0() int64 { return 1 }\n",
        "b.go": "package p\nfunc F1() int64 { return 2 }\n",
    }
    helper = _write_helper(
        tmp_path, json.dumps(_package_fixture(files)).encode()
    )
    paths = [_write_source(tmp_path, n, s) for n, s in files.items()]
    code, out, err = _run(capsys, _args(helper, *paths))
    assert code == 0 and err == ""
    manifest = json.loads(out)
    assert manifest["schema_version"] == "mumei.go-scalar-parameter-deps/v1"
    assert len(manifest["functions"]) == 2


def test_route_writes_the_manifest_to_an_output_file(tmp_path, capsys):
    helper = _write_helper(tmp_path, json.dumps(schema_fixture()).encode())
    source = _write_source(tmp_path, "main.go", SOURCE)
    output = tmp_path / "manifest.json"
    code, out, _ = _run(
        capsys, _args(helper, source, extra=["--output", str(output)])
    )
    assert code == 0 and out == ""
    assert json.loads(output.read_text())["functions"]


def test_unwritable_output_fails_closed(tmp_path, capsys):
    helper = _write_helper(tmp_path, json.dumps(schema_fixture()).encode())
    source = _write_source(tmp_path, "main.go", SOURCE)
    output = tmp_path / "absent-dir" / "manifest.json"
    code, out, err = _run(
        capsys, _args(helper, source, extra=["--output", str(output)])
    )
    assert code == 1 and out == "" and err.startswith("go-summaries: ")


def test_missing_helper_fails_closed(tmp_path, capsys):
    source = _write_source(tmp_path, "main.go", SOURCE)
    code, out, err = _run(
        capsys, _args(tmp_path / "absent-helper", source)
    )
    assert code == 1 and "not executable" in err and out == ""


def test_helper_failure_and_side_channel_fail_closed(tmp_path, capsys):
    source = _write_source(tmp_path, "main.go", SOURCE)
    for fail in ("exit", "stderr"):
        helper = _write_helper(tmp_path, None, fail=fail)
        code, out, err = _run(capsys, _args(helper, source))
        assert code == 1 and "produce a report" in err and out == ""


def test_non_ok_report_status_fails_closed(tmp_path, capsys):
    report = schema_fixture()
    report["status"] = "type_error"
    helper = _write_helper(tmp_path, json.dumps(report).encode())
    source = _write_source(tmp_path, "main.go", SOURCE)
    code, out, _ = _run(capsys, _args(helper, source))
    assert code == 1 and out == ""


def test_duplicate_source_basenames_fail(tmp_path, capsys):
    helper = _write_helper(tmp_path, json.dumps(schema_fixture()).encode())
    first = tmp_path / "one"
    second = tmp_path / "two"
    first.mkdir()
    second.mkdir()
    a = _write_source(first, "main.go", SOURCE)
    b = _write_source(second, "main.go", SOURCE)
    code, _, err = _run(capsys, _args(helper, a, b))
    assert code == 1 and "duplicate" in err


def test_zero_timeout_fails(tmp_path, capsys):
    helper = _write_helper(tmp_path, json.dumps(schema_fixture()).encode())
    source = _write_source(tmp_path, "main.go", SOURCE)
    code, _, err = _run(capsys, _args(helper, source, extra=["--timeout", "0"]))
    assert code == 1 and "timeout" in err


def test_target_arch_choices_cover_every_declared_target():
    parser = build_parser()
    action = next(a for a in parser._actions if a.dest == "target_arch")
    assert set(action.choices) == set(TARGETS)
