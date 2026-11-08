from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import asdict
from pathlib import Path

import pytest

from agent import control_flow, dataflow_facts
from agent.go_type_snapshot import (
    MAX_REPORT_BYTES,
    MAX_SOURCE_BYTES,
    PROFILE,
    SnapshotError,
    load_go_snapshot,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "package p\nfunc F() int64 { return 1 }\n"


@pytest.fixture(scope="session")
def go_types_helper(tmp_path_factory: pytest.TempPathFactory) -> Path:
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


def compiler_report(helper: Path, source: str, arch: str = "amd64") -> bytes:
    proc = subprocess.run(
        [str(helper)],
        input=json.dumps({"source": source, "target_arch": arch}).encode(),
        capture_output=True,
        timeout=30,
        check=True,
    )
    assert proc.stderr == b""
    return proc.stdout


def schema_fixture() -> dict:
    # A transport fixture, not a claim that JSON can authenticate compiler facts.
    digest = hashlib.sha256(SOURCE.encode()).hexdigest()
    start = SOURCE.index("F")
    binding_id = f"sha256:{digest}:{start}:0:{len(SOURCE)}"
    scalar = {
        "kind": "integer",
        "basic_name": "int64",
        "bit_width": 64,
        "signed": True,
        "type_id": "",
    }
    return {
        "profile": PROFILE,
        "source_sha256": digest,
        "target_arch": "amd64",
        "language_version": "go1.23",
        "compiler_version": "go1.27.1",
        "status": "ok",
        "bindings": [
            {
                "id": binding_id,
                "name": "F",
                "kind": "function",
                "span": {"start": start, "end": start + 1},
                "scope": {"start": 0, "end": len(SOURCE)},
                "type": {
                    "kind": "function",
                    "basic_name": "",
                    "bit_width": 0,
                    "signed": None,
                    "type_id": "",
                },
            }
        ],
        "functions": [
            {
                "binding_id": binding_id,
                "body": {"start": SOURCE.index("{") + 1, "end": SOURCE.index("}")},
                "parameters": [],
                "results": [{"binding_id": "", "type": scalar}],
                "method": False,
                "generic": False,
                "variadic": False,
            }
        ],
        "references": [],
        "calls": [],
        "gaps": [],
    }


def test_reader_is_pure_and_does_not_spawn_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("metadata consumption must not execute tools")

    monkeypatch.setattr(subprocess, "run", forbidden)
    snapshot = load_go_snapshot(
        json.dumps(schema_fixture()).encode(), SOURCE, target_arch="amd64"
    )
    assert snapshot.functions[0].results[0].type.bit_width == 64
    assert snapshot.profile == PROFILE
    assert snapshot.binding(snapshot.functions[0].binding_id).name == "F"
    assert snapshot.binding("missing") is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("profile", "unknown"),
        ("language_version", "go1.24"),
        ("compiler_version", "unknown"),
        ("source_sha256", "0" * 64),
        ("target_arch", "386"),
        ("status", "type_error"),
        ("status", "unsupported"),
        ("status", "parse_error"),
        ("status", "internal_error"),
        ("bindings", None),
        ("functions", {}),
        ("references", 42),
        ("calls", None),
        ("gaps", ""),
    ],
)
def test_wrong_or_missing_report_context_is_rejected(field: str, value: object) -> None:
    report = schema_fixture()
    report[field] = value
    with pytest.raises(SnapshotError):
        load_go_snapshot(json.dumps(report).encode(), SOURCE, target_arch="amd64")


@pytest.mark.parametrize(
    "case",
    [
        "extra_field",
        "missing_field",
        "binding_id",
        "binding_name",
        "binding_kind",
        "duplicate_binding",
        "span_negative",
        "span_reversed",
        "span_outside",
        "span_bool",
        "scope_outside",
        "bad_function_ref",
        "duplicate_function",
        "body_not_braced",
        "method_not_boolean",
        "dangling_parameter",
        "dangling_type",
        "wrong_integer_width",
        "wrong_integer_sign",
        "fake_type",
        "unknown_reference",
        "universe_with_binding",
        "unknown_target",
        "opaque_with_target",
        "unknown_call_kind",
        "unknown_owner",
        "argument_outside_call",
        "unknown_gap",
    ],
)
def test_inconsistent_or_malformed_metadata_fails_closed(case: str) -> None:
    report = schema_fixture()
    b, f = report["bindings"][0], report["functions"][0]
    scalar = f["results"][0]["type"]
    call = {
        "span": f["body"].copy(),
        "arguments": [],
        "owner": b["id"],
        "target": b["id"],
        "kind": "direct_local",
    }
    if case == "extra_field":
        report["command"] = "not executable"
    elif case == "missing_field":
        del report["profile"]
    elif case == "binding_id":
        b["id"] = "wrong"
    elif case == "binding_name":
        b["name"] = "wrong"
    elif case == "binding_kind":
        b["kind"] = "proved"
    elif case == "duplicate_binding":
        report["bindings"].append(b.copy())
    elif case == "span_negative":
        b["span"]["start"] = -1
    elif case == "span_reversed":
        b["span"]["end"] = b["span"]["start"] - 1
    elif case == "span_outside":
        b["span"]["end"] = len(SOURCE) + 1
    elif case == "span_bool":
        b["span"]["start"] = True
    elif case == "scope_outside":
        b["scope"]["end"] = len(SOURCE) + 1
    elif case == "bad_function_ref":
        f["binding_id"] = "wrong"
    elif case == "duplicate_function":
        report["functions"].append(f.copy())
    elif case == "body_not_braced":
        f["body"]["start"] += 1
    elif case == "method_not_boolean":
        f["method"] = 1
    elif case == "dangling_parameter":
        f["results"][0]["binding_id"] = "wrong"
    elif case == "dangling_type":
        scalar["type_id"] = "wrong"
    elif case == "wrong_integer_width":
        scalar["bit_width"] = 32
    elif case == "wrong_integer_sign":
        scalar["signed"] = False
    elif case == "fake_type":
        scalar["kind"] = "proved"
    elif case == "unknown_reference":
        report["references"] = [
            {"span": b["span"], "binding_id": "wrong", "kind": "local"}
        ]
    elif case == "universe_with_binding":
        report["references"] = [
            {"span": b["span"], "binding_id": b["id"], "kind": "universe"}
        ]
    elif case == "unknown_target":
        call["target"] = "wrong"
    elif case == "opaque_with_target":
        call["kind"] = "builtin"
    elif case == "unknown_call_kind":
        call["kind"] = "safe"
    elif case == "unknown_owner":
        call["owner"] = "wrong"
    elif case == "argument_outside_call":
        call["arguments"] = [{"start": 0, "end": len(SOURCE)}]
    elif case == "unknown_gap":
        report["gaps"] = [{"reason": "arbitrary diagnostic", "span": b["span"]}]
    if case in {
        "unknown_target",
        "opaque_with_target",
        "unknown_call_kind",
        "unknown_owner",
        "argument_outside_call",
    }:
        report["calls"] = [call]
    with pytest.raises(SnapshotError):
        load_go_snapshot(json.dumps(report).encode(), SOURCE, target_arch="amd64")


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"{",
        b"\xff",
        b"[]",
        b"null",
        b'{"profile":1,"profile":2}',
        b"[" * 2000 + b"]" * 2000,
    ],
)
def test_bad_json_is_rejected(payload: bytes) -> None:
    with pytest.raises(SnapshotError):
        load_go_snapshot(payload, SOURCE, target_arch="amd64")


def test_limits_encoding_and_unknown_target() -> None:
    for payload, source, arch in [
        (b" " * (MAX_REPORT_BYTES + 1), SOURCE, "amd64"),
        (b"{}", " " * (MAX_SOURCE_BYTES + 1), "amd64"),
        (b"{}", "\ud800", "amd64"),
        (b"{}", SOURCE, "unknown"),
    ]:
        with pytest.raises(SnapshotError):
            load_go_snapshot(payload, source, target_arch=arch)


@pytest.mark.parametrize("arch,width", [("amd64", 64), ("386", 32), ("arm64", 64)])
def test_real_compiler_widths_aliases_and_named_results(
    go_types_helper: Path, arch: str, width: int
) -> None:
    source = "package p; type Index int64; type Small = int8; func F(x Index, n int, s Small) (out Index) { return x }"
    snapshot = load_go_snapshot(
        compiler_report(go_types_helper, source, arch), source, target_arch=arch
    )
    by_name = {b.name: b for b in snapshot.bindings}
    assert by_name["x"].type.bit_width == 64
    assert by_name["x"].type.type_id == by_name["Index"].id
    assert by_name["s"].type.bit_width == 8
    assert by_name["n"].type.bit_width == width
    assert snapshot.functions[0].results[0].binding_id == by_name["out"].id
    with pytest.raises(SnapshotError):
        load_go_snapshot(
            compiler_report(go_types_helper, source), source, target_arch="386"
        )


def test_source_type_names_are_not_heuristic_widths(go_types_helper: Path) -> None:
    source = "package p; type int64 = int8; func F(x int64) int64 { return x }"
    snapshot = load_go_snapshot(
        compiler_report(go_types_helper, source), source, target_arch="amd64"
    )
    assert snapshot.functions[0].parameters[0].type.bit_width == 8


def test_shadowing_reassignment_and_indirect_callee_remain_distinct(
    go_types_helper: Path,
) -> None:
    source = """package p
func G(x int64) int64 { return x }
func F(x int64) int64 {
 x, y := G(x), x
 { x := y; _ = x }
 x = y
 return x
}
func H(G func(int64) int64, x int64) int64 { return G(x) }
"""
    snapshot = load_go_snapshot(
        compiler_report(go_types_helper, source), source, target_arch="amd64"
    )
    xs = [b for b in snapshot.bindings if b.name == "x"]
    f = next(
        f for f in snapshot.functions if snapshot.binding(f.binding_id).name == "F"
    )
    outer = f.parameters[0].binding_id
    for text in ["x, y :=", "x = y", "x\n}"]:
        offset = source.index(text)
        assert (
            next(r for r in snapshot.references if r.span.start == offset).binding_id
            == outer
        )
    assert len({b.id for b in xs}) == 4
    assert [c.kind for c in snapshot.calls] == ["direct_local", "indirect_or_selector"]
    assert snapshot.calls[1].target == ""
    assert any(
        g.reason == "call_not_summarized_indirect_or_selector" for g in snapshot.gaps
    )


def test_unicode_file_byte_spans_join_to_existing_body_codepoint_cfg(
    go_types_helper: Path,
) -> None:
    source = "// 雪\npackage p\nfunc F(値 int64) int64 {\n// é\n if 値 > 0 { return 値 }; return 0\n}"
    snapshot = load_go_snapshot(
        compiler_report(go_types_helper, source), source, target_arch="amd64"
    )
    fn = snapshot.functions[0]
    assert fn.body is not None
    body = source.encode()[fn.body.start : fn.body.end].decode()
    cfg = snapshot.cfg_for_function(source, fn.binding_id).graph
    assert cfg is not None
    assert cfg == control_flow.build_go_cfg(body).graph
    assert cfg.source_sha256 == hashlib.sha256(body.encode()).hexdigest()
    for node in cfg.nodes:
        if node.kind == "return":
            assert body[node.span.start : node.span.end].startswith("return")
    value = next(b for b in snapshot.bindings if b.name == "値")
    assert source.encode()[value.span.start : value.span.end].decode() == "値"
    damaged = json.loads(compiler_report(go_types_helper, source))
    damaged["bindings"][
        next(i for i, b in enumerate(damaged["bindings"]) if b["name"] == "値")
    ]["span"]["end"] -= 1
    with pytest.raises(SnapshotError):
        load_go_snapshot(json.dumps(damaged).encode(), source, target_arch="amd64")
    facts = dataflow_facts.analyze_function(body, "go")
    assert facts is not None and facts.cfg == cfg


def test_callee_change_invalidates_entire_unit_even_with_unchanged_caller_body(
    go_types_helper: Path,
) -> None:
    source = "package p; func G() int64 { return 1 }; func F() int64 { return G() }"
    snapshot = load_go_snapshot(
        compiler_report(go_types_helper, source), source, target_arch="amd64"
    )
    f = next(
        f for f in snapshot.functions if snapshot.binding(f.binding_id).name == "F"
    )
    changed = source.replace("return 1", "return 2")
    with pytest.raises(SnapshotError):
        snapshot.cfg_for_function(changed, f.binding_id)
    with pytest.raises(SnapshotError):
        load_go_snapshot(
            compiler_report(go_types_helper, source), changed, target_arch="amd64"
        )
    updated = load_go_snapshot(
        compiler_report(go_types_helper, changed), changed, target_arch="amd64"
    )
    assert not ({b.id for b in snapshot.bindings} & {b.id for b in updated.bindings})
    with pytest.raises(SnapshotError):
        updated.cfg_for_function(changed, f.binding_id)


@pytest.mark.parametrize(
    "fragment",
    [
        "func F(a any) { switch x := a.(type) { case int64: _ = x; case string: _ = x } }",
        "type T struct{}; func (T) M() int64 { return 1 }; func F(x T) int64 { return x.M() }",
        "type I interface{M() int64}; func F(x I) int64 { return x.M() }",
        "func Id[T any](x T) T { return x }; func F(x int64) int64 { return Id[int64](x) }",
        "func Ext(int64) int64; func F(x int64) int64 { return Ext(x) }",
        "func F(x int64) uint64 { return uint64(x) }",
        "func G() {}; func F() { defer G(); go G() }",
    "func F() int64 { return (func() int64 { return 1 })() }",
    "func F(f func()) { _ = f }",
        "func G() int64 { return 1 }; var V = G(); func F() int64 { return V }",
        "func _(x int64) int64 { return x }",
        "func F() { label: goto label }",
    ],
)
def test_unsupported_value_and_call_semantics_are_explicit_not_safe_facts(
    go_types_helper: Path, fragment: str
) -> None:
    source = "package p; " + fragment
    snapshot = load_go_snapshot(
        compiler_report(go_types_helper, source), source, target_arch="amd64"
    )
    assert snapshot.gaps
    assert all(not c.target for c in snapshot.calls if c.kind != "direct_local")
    serialized = json.dumps(asdict(snapshot))
    for key in ("verification_status", "lean_verified", "proved", "seal_grade"):
        assert key not in serialized


@pytest.mark.parametrize(
    "source",
    [
        "package p; func F() int64 { return missing }",
        "package p; func F( {",
        'package p; import "fmt"; func F() {}',
        "//go:build linux\npackage p; func F() {}",
    ],
)
def test_non_ok_real_compiler_reports_never_supply_partial_metadata(
    go_types_helper: Path, source: str
) -> None:
    report = compiler_report(go_types_helper, source)
    assert json.loads(report)["bindings"] == []
    with pytest.raises(SnapshotError):
        load_go_snapshot(report, source, target_arch="amd64")


def test_metadata_and_errors_do_not_echo_secret_values(
    go_types_helper: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    sentinel = "obviously-fake-c06-reader-secret-sentinel"
    monkeypatch.setenv("OPENAI_API_KEY", sentinel)
    for source in [
        f'// {sentinel}\npackage p; const S = "{sentinel}"',
        f'package p; var S int64 = "{sentinel}"',
    ]:
        report = compiler_report(go_types_helper, source)
        assert sentinel.encode() not in report
        try:
            snapshot = load_go_snapshot(report, source, target_arch="amd64")
            assert sentinel not in repr(snapshot)
        except SnapshotError as exc:
            assert sentinel not in str(exc)
    captured = capsys.readouterr()
    assert sentinel not in captured.out + captured.err
