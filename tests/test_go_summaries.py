"""Route tests for `python -m agent go-summaries`.

A stub helper stands in for a provisioned go-types binary: the route is
tested against the same declared-report contract the real helper speaks,
never against a live compiler.
"""
import hashlib
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from agent.go_summaries import build_check_parser, build_parser, main, main_check
from agent.go_type_snapshot import PACKAGE_PROFILE, TARGETS
from tests.test_go_type_snapshot import SOURCE, schema_fixture

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def real_go_types(tmp_path_factory: pytest.TempPathFactory) -> Path:
    go = shutil.which("go")
    if go is None:
        pytest.skip(
            "Optional Go compiler integration requires Go 1.26+ (mandatory in CI)"
        )
    binary = tmp_path_factory.mktemp("go-types") / "go-types"
    env = {
        **os.environ,
        "GOTOOLCHAIN": "local",
        "GOPROXY": "off",
        "GOSUMDB": "off",
        "GOWORK": "off",
    }
    subprocess.run(
        [go, "build", "-o", str(binary), "."],
        cwd=ROOT / "tools/go-types",
        env=env,
        capture_output=True,
        check=True,
        timeout=120,
    )
    return binary


def _write_helper(
    tmp_path: Path, payload: bytes | None, *, fail: str = ""
) -> Path:
    helper = tmp_path / "go-types-stub"
    if fail == "exit":
        body = "echo 'broken' >&2; exit 3"
    elif fail == "stderr":
        body = "echo 'noise' >&2; cat >/dev/null; echo '{}'"
    elif fail == "capture":
        report = tmp_path / "report.json"
        report.write_bytes(payload)
        body = f"cat > {tmp_path}/captured.json; cat {report}"
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


def _run_check(capsys, argv: list[str]):
    try:
        code = main_check(build_check_parser().parse_args(argv))
    except SystemExit as exc:
        code = exc.code
    out = capsys.readouterr()
    return code, out.out, out.err


def _check_args(helper: Path, manifest: Path, *sources: Path, extra=()):
    return _args(
        helper, *sources, extra=["--manifest", str(manifest), *extra]
    )


def _produce_manifest(tmp_path, capsys, helper: Path, *sources: Path):
    """Run the produce route and persist its manifest for a check run."""
    code, out, err = _run(capsys, _args(helper, *sources))
    assert code == 0 and err == ""
    manifest = tmp_path / "manifest.json"
    manifest.write_text(out, encoding="utf-8")
    return manifest


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


def test_output_equal_to_a_declared_source_fails(tmp_path, capsys):
    helper = _write_helper(tmp_path, json.dumps(schema_fixture()).encode())
    source = _write_source(tmp_path, "main.go", SOURCE)
    code, out, err = _run(
        capsys, _args(helper, source, extra=["--output", str(source)])
    )
    assert code == 1 and out == "" and "overwrite" in err
    assert source.read_text() == SOURCE


def test_unresolvable_output_path_fails_closed(tmp_path, capsys):
    """A symlink loop under --output resolves with RuntimeError, which
    must surface as a clean failure, not a traceback."""
    helper = _write_helper(tmp_path, json.dumps(schema_fixture()).encode())
    source = _write_source(tmp_path, "main.go", SOURCE)
    os.symlink("loop", tmp_path / "loop")
    code, out, err = _run(
        capsys,
        _args(
            helper,
            source,
            extra=["--output", str(tmp_path / "loop" / "m.json")],
        ),
    )
    assert code == 1 and out == ""
    assert err.startswith("go-summaries: ") and "Traceback" not in err


def test_request_over_the_helper_bound_fails(tmp_path, capsys):
    helper = _write_helper(tmp_path, json.dumps(schema_fixture()).encode())
    paths = [
        _write_source(
            tmp_path, f"part{i}.go", "package p\n// " + "x" * (60 * 1024)
        )
        for i in range(9)
    ]
    code, out, err = _run(capsys, _args(helper, *paths))
    assert code == 1 and out == "" and "helper bound" in err


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


def test_imports_declare_their_units_in_the_request(tmp_path, capsys):
    files = {
        "a.go": "package p\nimport l \"my/lib\"\nfunc F0() int64 { return l.G(1) }\n",
        "b.go": "package p\nfunc F1() int64 { return 2 }\n",
    }
    helper = _write_helper(
        tmp_path, json.dumps(_package_fixture(files)).encode(), fail="capture"
    )
    lib = _write_source(
        tmp_path, "lib.go", "package lib\nfunc G(x int64) int64 { return x }\n"
    )
    paths = [_write_source(tmp_path, n, s) for n, s in files.items()]
    code, _, err = _run(
        capsys, _args(helper, *paths, extra=["--import", f"my/lib={lib}"])
    )
    assert code == 0 and err == ""
    request = json.loads((tmp_path / "captured.json").read_text())
    assert [s["name"] for s in request["sources"]] == ["a.go", "b.go"]
    assert request["imports"] == [
        {
            "path": "my/lib",
            "sources": [{"name": "lib.go", "source": lib.read_text()}],
        }
    ]


def test_import_requires_a_package_unit(tmp_path, capsys):
    helper = _write_helper(tmp_path, json.dumps(schema_fixture()).encode())
    source = _write_source(tmp_path, "main.go", SOURCE)
    lib = _write_source(tmp_path, "lib.go", "package lib\n")
    code, _, err = _run(
        capsys, _args(helper, source, extra=["--import", f"my/lib={lib}"])
    )
    assert code == 1 and "package unit" in err


def test_output_equal_to_a_declared_import_file_fails(tmp_path, capsys):
    files = {
        "a.go": "package p\nimport l \"my/lib\"\nfunc F0() int64 { return l.G(1) }\n",
        "b.go": "package p\nfunc F1() int64 { return 2 }\n",
    }
    helper = _write_helper(
        tmp_path, json.dumps(_package_fixture(files)).encode()
    )
    lib_source = "package lib\nfunc G(x int64) int64 { return x }\n"
    lib = _write_source(tmp_path, "lib.go", lib_source)
    paths = [_write_source(tmp_path, n, s) for n, s in files.items()]
    code, out, err = _run(
        capsys,
        _args(
            helper,
            *paths,
            extra=["--import", f"my/lib={lib}", "--output", str(lib)],
        ),
    )
    assert code == 1 and out == "" and "overwrite" in err
    assert lib.read_text() == lib_source


def test_malformed_and_duplicate_import_specs_fail(tmp_path, capsys):
    helper = _write_helper(tmp_path, json.dumps(schema_fixture()).encode())
    source = _write_source(tmp_path, "main.go", SOURCE)
    lib = _write_source(tmp_path, "lib.go", "package lib\n")
    code, _, err = _run(
        capsys, _args(helper, source, extra=["--import", "my/lib"])
    )
    assert code == 1 and "<IMPORT_PATH>=<FILE>" in err
    other = tmp_path / "other"
    other.mkdir()
    dup = _write_source(other, "lib.go", "package lib\n")
    code, _, err = _run(
        capsys,
        _args(
            helper,
            source,
            extra=["--import", f"my/lib={lib}", "--import", f"my/lib={dup}"],
        ),
    )
    assert code == 1 and "duplicate" in err


def test_real_helper_round_trip(tmp_path, capsys, real_go_types):
    """The route speaks the helper's real wire contract, not only a stub's."""
    source = _write_source(
        tmp_path,
        "main.go",
        "package p\n"
        "func F(x int64) int64 { return x }\n"
        "func G(y int64) int64 { return F(y) }\n",
    )
    code, out, err = _run(capsys, _args(real_go_types, source))
    assert code == 0 and err == ""
    manifest = json.loads(out)
    assert manifest["schema_version"] == "mumei.go-scalar-parameter-deps/v1"
    assert len(manifest["functions"]) == 2
    # The G -> F call edge must survive the route end-to-end: a transfer
    # whose result depends on the actual would be invisible to a
    # function-count-only assertion.
    calls = [
        call
        for entry in manifest["functions"]
        for call in entry["calls"]
    ]
    assert calls and any(call["result"] for call in calls)


def test_real_helper_package_round_trip(tmp_path, capsys, real_go_types):
    files = {
        "a.go": "package p\nfunc F(x int64) int64 { return x }\n",
        "b.go": "package p\nfunc G(y int64) int64 { return F(y) }\n",
    }
    paths = [_write_source(tmp_path, n, s) for n, s in files.items()]
    code, out, err = _run(capsys, _args(real_go_types, *paths))
    assert code == 0 and err == ""
    manifest = json.loads(out)
    assert len(manifest["functions"]) == 2
    calls = [
        call
        for entry in manifest["functions"]
        for call in entry["calls"]
    ]
    assert calls and any(call["result"] for call in calls)


def test_check_round_trip_marks_everything_reusable(tmp_path, capsys):
    files = {
        "a.go": "package p\nfunc F0() int64 { return 1 }\n",
        "b.go": "package p\nfunc F1() int64 { return 2 }\n",
    }
    helper = _write_helper(
        tmp_path, json.dumps(_package_fixture(files)).encode()
    )
    paths = [_write_source(tmp_path, n, s) for n, s in files.items()]
    manifest_path = _produce_manifest(tmp_path, capsys, helper, *paths)
    manifest = json.loads(manifest_path.read_text())
    code, out, err = _run_check(
        capsys, _check_args(helper, manifest_path, *paths)
    )
    assert code == 0 and err == ""
    report = json.loads(out)
    assert report["schema_version"] == "mumei.go-summary-check/v1"
    assert report["context_match"] is True
    ids = [f["binding_id"] for f in manifest["functions"]]
    assert sorted(report["reusable"]) == sorted(ids)
    assert report["stale"] == [] and report["missing"] == []


def test_check_partitions_stale_and_missing(tmp_path, capsys):
    files = {
        "a.go": "package p\nfunc F0() int64 { return 1 }\n",
        "b.go": "package p\nfunc F1() int64 { return 2 }\n",
    }
    helper = _write_helper(
        tmp_path, json.dumps(_package_fixture(files)).encode()
    )
    paths = [_write_source(tmp_path, n, s) for n, s in files.items()]
    manifest_path = _produce_manifest(tmp_path, capsys, helper, *paths)
    manifest = json.loads(manifest_path.read_text())
    first = manifest["functions"][0]
    first["calls"] = [
        {
            "span": {"file": 0, "start": 0, "end": 1},
            "target": "absent-target",
            "arguments": [],
            "result": [],
        }
    ]
    manifest["functions"].append(
        {
            "binding_id": "gone-fn",
            "key": "gone",
            "parameters": [],
            "calls": [],
            "gaps": [],
        }
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    code, out, err = _run_check(
        capsys, _check_args(helper, manifest_path, *paths)
    )
    assert code == 0 and err == ""
    report = json.loads(out)
    assert report["stale"] == [first["binding_id"]]
    assert report["missing"] == ["gone-fn"]
    assert report["reusable"] == [
        manifest["functions"][1]["binding_id"]
    ]


def test_check_rejects_a_malformed_manifest(tmp_path, capsys):
    helper = _write_helper(tmp_path, json.dumps(schema_fixture()).encode())
    source = _write_source(tmp_path, "main.go", SOURCE)
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    code, out, err = _run_check(capsys, _check_args(helper, bad, source))
    assert code == 1 and out == "" and "not JSON" in err
    bad.write_text(
        json.dumps(
            {
                "schema_version": "mumei.other/v9",
                "context_key": "x",
                "functions": [],
            }
        ),
        encoding="utf-8",
    )
    code, out, err = _run_check(capsys, _check_args(helper, bad, source))
    assert code == 1 and out == "" and "malformed" in err


def test_check_output_equal_to_the_manifest_fails(tmp_path, capsys):
    helper = _write_helper(tmp_path, json.dumps(schema_fixture()).encode())
    source = _write_source(tmp_path, "main.go", SOURCE)
    manifest_path = _produce_manifest(tmp_path, capsys, helper, source)
    original = manifest_path.read_text()
    code, out, err = _run_check(
        capsys,
        _check_args(
            helper, manifest_path, source, extra=["--output", str(manifest_path)]
        ),
    )
    assert code == 1 and out == "" and "overwrite" in err
    assert manifest_path.read_text() == original


def test_real_helper_check_round_trip(tmp_path, capsys, real_go_types):
    """The check route reads back what the produce route emitted through
    the real helper: every function stays reusable."""
    source = _write_source(
        tmp_path,
        "main.go",
        "package p\n"
        "func F(x int64) int64 { return x }\n"
        "func G(y int64) int64 { return F(y) }\n",
    )
    manifest_path = _produce_manifest(
        tmp_path, capsys, real_go_types, source
    )
    manifest = json.loads(manifest_path.read_text())
    code, out, err = _run_check(
        capsys, _check_args(real_go_types, manifest_path, source)
    )
    assert code == 0 and err == ""
    report = json.loads(out)
    assert report["context_match"] is True
    ids = [f["binding_id"] for f in manifest["functions"]]
    assert sorted(report["reusable"]) == sorted(ids)
    assert report["stale"] == [] and report["missing"] == []


def test_real_helper_import_round_trip(tmp_path, capsys, real_go_types):
    """A declared import unit resolves through the real helper: the call
    into the imported package must surface as an imported transfer in
    the emitted manifest, not vanish as an unresolved gap."""
    files = {
        "a.go": (
            "package p\n"
            'import l "my/lib"\n'
            "func F(x int64) int64 { return l.H(x) }\n"
        ),
        "b.go": "package p\nfunc G(y int64) int64 { return F(y) }\n",
    }
    lib = _write_source(
        tmp_path,
        "lib.go",
        "package lib\nfunc H(y int64) int64 { return y }\n",
    )
    paths = [_write_source(tmp_path, n, s) for n, s in files.items()]
    code, out, err = _run(
        capsys,
        _args(real_go_types, *paths, extra=["--import", f"my/lib={lib}"]),
    )
    assert code == 0 and err == ""
    manifest = json.loads(out)
    calls = [
        call
        for entry in manifest["functions"]
        for call in entry["calls"]
    ]
    assert calls and any(call.get("imported") for call in calls)
