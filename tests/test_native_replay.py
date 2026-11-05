"""Native replay: run audited functions natively and check the extracted contract on the result."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent.audit import AuditPipeline, build_parser
from agent.code_to_spec import CodeToSpecResult
from agent.config import AgentConfig
from agent.native_replay import (
    NativeReplayer,
    NativeRunner,
    Param,
    Unexpressible,
    atom_params,
    boundary_inputs,
    coerce_value,
    contract_check_module,
    counterexample_input,
    go_signature,
    mm_literal,
    native_replay_violations,
    pin_clause,
    reconcile_body_ports,
    rust_signature,
)

CLAMP = {
    "name": "clamp",
    "params": [{"name": "x", "type": "i64"}, {"name": "hi", "type": "i64"}],
    "return_type": "i64",
    "requires": "true",
    "ensures": "result <= hi",
}
PY_CLAMP = "def clamp(x, hi):\n    if x > hi:\n        return x\n    return x\n"
PROVEN = {"success": True, "report": {"status": "verified"}}
REFUTED = {"success": False, "report": {"status": "failed", "diagnostics": [{"message": "Verification Error: Postcondition violated"}]}}
EXCLUDED = {"success": False, "report": {"status": "failed", "diagnostics": [
    {"message": "requires_unsat: requires clause is unsatisfiable before proof attempt"}]}}


class FakeMumei:
    """Decides ``result <= hi`` style contracts from the pinned module text."""

    def __init__(self) -> None:
        self.modules: list[str] = []

    def verify(self, path: str, report_dir: str) -> dict:
        text = Path(path).read_text(encoding="utf-8")
        self.modules.append(text)
        pins = dict(re.findall(r"(\w+) == (-?\d+|\(0 - \d+\))", text))
        value = lambda v: -int(v[5:-1]) if v.startswith("(0 - ") else int(v)  # noqa: E731
        body = re.search(r"body: \{\s*(.+?)\s*\}", text, re.S).group(1)
        if "ensures: true;" in text:
            return PROVEN
        if not re.fullmatch(r"-?\d+|\(0 - \d+\)|true|false", body):
            return {"success": False, "report": {"status": "error"}}
        if "hi" in pins:
            return PROVEN if value(body) <= value(pins["hi"]) else REFUTED
        return PROVEN


@pytest.mark.parametrize(
    "raw,kind,expected",
    [("3", "int", 3), ("(- 4)", "int", -4), (-2, "int", -2), ("true", "bool", True), (False, "bool", False),
     ("[1, -2]", "int_array", [1, -2]), ("1_000", "int", 1000)],
)
def test_coerce_value(raw, kind, expected):
    assert coerce_value(raw, kind) == expected


@pytest.mark.parametrize("raw,kind", [("x", "int"), (True, "int"), ("yes", "bool"), ("[1", "int_array"),
                                       (list(range(65)), "int_array")])
def test_coerce_value_rejects(raw, kind):
    with pytest.raises(Unexpressible):
        coerce_value(raw, kind)


def test_atom_params_rejects_unsupported_types():
    assert atom_params(CLAMP) == [Param("x", "int"), Param("hi", "int")]
    assert atom_params({"params": [{"name": "xs", "type": "[i64]"}, {"name": "b", "type": "bool"}]}) == [
        Param("xs", "int_array"), Param("b", "bool")]
    assert atom_params({"params": [{"name": "s", "type": "Str"}]}) is None


def test_counterexample_input_fills_free_parameters():
    assert counterexample_input(atom_params(CLAMP), {"x": "5"}) == {"x": 5, "hi": 0}


def test_boundary_inputs_vary_one_parameter_and_are_capped():
    inputs = boundary_inputs(atom_params(CLAMP))
    assert inputs[0] == {"x": 0, "hi": 0}
    assert {"x": -1, "hi": 0} in inputs and {"x": 0, "hi": 1} in inputs
    assert len(inputs) == 12 and len({json.dumps(i, sort_keys=True) for i in inputs}) == 12


def test_pin_clause_and_literals():
    params = [Param("x", "int"), Param("b", "bool"), Param("xs", "int_array")]
    assert pin_clause(params, {"x": -3, "b": False, "xs": [7]}) == "x == (0 - 3) && !b && len(xs) == 1 && xs[0] == 7"
    assert mm_literal(True) == "true"
    with pytest.raises(Unexpressible):
        mm_literal("text")


def test_contract_check_module_pins_inputs_and_result():
    text = contract_check_module(CLAMP, atom_params(CLAMP), {"x": 1, "hi": 0}, 1, [])
    assert "atom clamp(x: i64, hi: i64) -> i64 {" in text
    assert "requires: (true) && x == 1 && hi == 0;" in text
    assert "ensures: result <= hi;" in text and "body: {\n        1\n    }" in text
    assert "trusted" not in text


def test_contract_check_module_includes_called_atoms_as_trusted():
    helper = {"name": "cap", "params": [], "return_type": "i64", "requires": "true", "ensures": "result >= 0"}
    atom = {**CLAMP, "ensures": "result <= cap()"}
    assert "trusted atom cap() -> i64" in contract_check_module(atom, atom_params(atom), {"x": 0, "hi": 0}, 0, [helper])


def test_go_and_rust_signatures():
    assert go_signature("func Div(a, b int32, xs []int64) (int32, error) {\n}") == (
        ["int32", "int32", "[]int64"], ["int32", "error"])
    assert go_signature("func (s *S) M(a int) int {\n}") is None
    assert rust_signature("pub fn f(a: i64, xs: &[u32]) -> i64 {") == ["i64", "&[u32]"]
    assert rust_signature("fn m(&self, a: i64) -> i64 {") is None


def test_python_runner_returns_values_and_exception_types(tmp_path):
    source = tmp_path / "calc.py"
    source.write_text("def div(a, b):\n    print('noise')\n    return a // b\n", encoding="utf-8")
    rows = NativeRunner().run("python", source, source.read_text(), "div", [[7, 2], [1, 0]])
    assert rows == [{"ok": True, "value": 3}, {"ok": False, "error": "ZeroDivisionError"}]


def test_runner_rejects_functions_it_cannot_find(tmp_path):
    source = tmp_path / "calc.py"
    source.write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(Unexpressible):
        NativeRunner().run("python", source, source.read_text(), "missing", [[1]])


def _replay(tmp_path, source_code=PY_CLAMP, atom=CLAMP, **kwargs):
    source = tmp_path / "clamp.py"
    source.write_text(source_code, encoding="utf-8")
    mumei = FakeMumei()
    out = NativeReplayer(mumei).replay(source, source_code, "python", {"atoms": [atom]}, **kwargs)
    return out, mumei


def test_replay_confirms_a_counterexample_the_native_code_reproduces(tmp_path):
    ports = [{"function": "clamp", "outcome": "refuted", "counterexample": {"x": "5", "hi": "2"}}]
    out, _ = _replay(tmp_path, body_ports=ports)
    first = out[0]
    assert first["source"] == "body_port" and first["input"] == {"x": 5, "hi": 2}
    assert first["native"] == {"ok": True, "value": 5} and first["verdict"] == "violates"
    assert native_replay_violations(out)[0].startswith("native-replay: clamp: the native function breaks")
    assert reconcile_body_ports(ports, out) == set() and ports[0]["native_replay"] == "reproduced"


def test_replay_drops_a_port_refutation_the_native_code_does_not_reproduce(tmp_path):
    fixed = "def clamp(x, hi):\n    return hi if x > hi else x\n"
    ports = [{"function": "clamp", "outcome": "refuted", "counterexample": {"x": "5", "hi": "2"}}]
    out, _ = _replay(tmp_path, fixed, body_ports=ports)
    assert not native_replay_violations(out)
    assert reconcile_body_ports(ports, out) == {"clamp"} and ports[0]["native_replay"] == "not_reproduced"


def test_a_proven_port_of_a_violating_function_is_a_port_mismatch(tmp_path):
    out, _ = _replay(tmp_path)
    ports = [{"function": "clamp", "outcome": "proven"}]
    reconcile_body_ports(ports, out)
    assert ports[0]["native_replay"] == "port_mismatch"


def test_raised_inputs_are_checked_against_requires_only(tmp_path):
    atom = {**CLAMP, "name": "boom"}
    out, mumei = _replay(tmp_path, "def boom(x, hi):\n    raise ValueError('no')\n", atom)
    assert out and all(r["verdict"] == "raised" for r in out)
    assert all("ensures: true;" in m for m in mumei.modules)
    assert not native_replay_violations(out)


def test_boundary_inputs_outside_requires_are_left_out(tmp_path):
    mumei = MagicMock()
    mumei.verify.return_value = EXCLUDED
    source = tmp_path / "clamp.py"
    source.write_text(PY_CLAMP, encoding="utf-8")
    cex = [{"function_name": "clamp", "counterexample": {"x": "1", "hi": "0"}}]
    out = NativeReplayer(mumei).replay(source, PY_CLAMP, "python", {"atoms": [CLAMP]}, counterexample_values=cex)
    assert [r["source"] for r in out] == ["counterexample"] and out[0]["verdict"] == "outside_requires"


def test_unsupported_signatures_and_languages_are_recorded(tmp_path):
    atom = {**CLAMP, "params": [{"name": "s", "type": "Str"}]}
    out, _ = _replay(tmp_path, atom=atom)
    assert [r["verdict"] for r in out] == ["unsupported"]
    source = tmp_path / "c.sol"
    source.write_text("contract C {}", encoding="utf-8")
    out = NativeReplayer(FakeMumei()).replay(source, "", "solidity", {"atoms": [CLAMP]})
    assert out[0]["verdict"] == "unsupported" and "solidity" in out[0]["reason"]


def test_results_of_other_types_are_unexpressible(tmp_path):
    out, _ = _replay(tmp_path, "def clamp(x, hi):\n    return 'x'\n")
    assert out and all(r["verdict"] == "unexpressible" for r in out)


def test_counterexample_values_that_do_not_parse_are_unexpressible(tmp_path):
    cex = [{"function_name": "clamp", "counterexample": {"x": "abc"}}]
    out, _ = _replay(tmp_path, counterexample_values=cex)
    assert out[0]["source"] == "counterexample" and out[0]["verdict"] == "unexpressible"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_typescript_runner_calls_unexported_functions(tmp_path):
    source = tmp_path / "calc.ts"
    source.write_text("function add(a: number, b: number): number {\n  return a + b;\n}\n", encoding="utf-8")
    rows = NativeRunner().run("typescript", source, source.read_text(), "add", [[1, 2]])
    assert rows == [{"ok": True, "value": 3}]
    assert "__mumeiNativeReplayTarget" not in source.read_text()


def _pipeline(tmp_path, replayer, porter=None):
    source = tmp_path / "clamp.py"
    source.write_text(PY_CLAMP, encoding="utf-8")
    extractor = MagicMock()
    extractor.extract_from_file.return_value = CodeToSpecResult(
        success=True, natural_language_spec="clamp x to hi", forge_task_spec={"atoms": [CLAMP]},
        detected_language="python")
    foreign = MagicMock()
    foreign.verify.return_value = {"success": True, "verification": {"success": True, "report": {"status": "verified"}}}
    cross = MagicMock()
    cross.validate_spec_vs_impl.return_value = MagicMock(gaps=[], issues=[])
    pipeline = AuditPipeline(
        AgentConfig(api_key=""), code_to_spec_extractor=extractor, foreign_code_verifier=foreign,
        cross_validator=cross, mumei_client=MagicMock(), spec_health_checker=MagicMock(),
        body_porter=porter, native_replayer=replayer)
    return pipeline, source


def _porter(*entries):
    porter = MagicMock()
    porter.port.return_value = list(entries)
    return porter


def test_native_replay_is_off_by_default(tmp_path):
    replayer = MagicMock()
    pipeline, source = _pipeline(tmp_path, replayer)
    result = pipeline.audit_file(source, "python")
    replayer.replay.assert_not_called()
    assert result.native_replays == [] and result.finding_counts["confirmed"] == 0


def test_a_confirmed_replay_is_a_code_finding(tmp_path):
    pipeline, source = _pipeline(tmp_path, NativeReplayer(FakeMumei()))
    result = pipeline.audit_file(source, "python", enable_native_replay=True)
    assert result.success is False and result.verification_status == "refuted"
    assert any(v.startswith("native-replay: clamp:") for v in result.verification_violations)
    assert result.finding_counts["confirmed"] == result.finding_counts["code"] > 0
    assert "native_replays:" in result.report or "native_replays" in result.report


def test_a_port_refutation_the_native_code_meets_is_dropped(tmp_path):
    port = {"function": "clamp", "outcome": "refuted", "reason": "Postcondition violated", "body": "x",
            "counterexample": {"x": "5", "hi": "2"}}
    replayer = MagicMock()
    replayer.replay.return_value = [{"function": "clamp", "input": {"x": 5, "hi": 2}, "source": "body_port",
                                     "native": {"ok": True, "value": 2}, "verdict": "meets", "reason": ""}]
    pipeline, source = _pipeline(tmp_path, replayer, _porter(port))
    result = pipeline.audit_file(source, "python", enable_body_port=True, enable_native_replay=True)
    assert result.body_ports[0]["native_replay"] == "not_reproduced"
    assert not any(v.startswith("body-port:") for v in result.verification_violations)
    assert result.success is True and result.verification_status != "refuted"


def test_cli_flag():
    assert build_parser().parse_args(["--code-file", "f.py", "--enable-native-replay"]).enable_native_replay is True
    assert build_parser().parse_args(["--code-file", "f.py"]).enable_native_replay is False


SENTINEL_NUMBER = "987654321012345"


def test_unparsable_counterexample_values_are_not_echoed():
    with pytest.raises(Unexpressible) as exc:
        coerce_value("sk-FAKE-SENTINEL-not-a-number", "int")
    assert "SENTINEL" not in str(exc.value)


def test_native_error_text_is_reduced_to_a_type_name(tmp_path):
    from agent.native_replay import MARK, _parse_marked

    rows = _parse_marked(
        f'{MARK}{{"ok": false, "error": "sk-FAKE-SENTINEL leaked here"}}\n{MARK}{{"ok": false, "error": "RangeError"}}\n'
    )
    assert rows == [{"ok": False, "error": "exception"}, {"ok": False, "error": "RangeError"}]


def test_sensitive_values_are_redacted_from_native_results(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", SENTINEL_NUMBER)
    out, _ = _replay(tmp_path, f"def clamp(x, hi):\n    return {SENTINEL_NUMBER}\n")
    assert out and SENTINEL_NUMBER not in json.dumps(out)
    assert all(SENTINEL_NUMBER not in v for v in native_replay_violations(out))


def test_a_single_atom_spec_is_replayed(tmp_path):
    source = tmp_path / "clamp.py"
    source.write_text(PY_CLAMP, encoding="utf-8")
    out = NativeReplayer(FakeMumei()).replay(source, PY_CLAMP, "python", dict(CLAMP))
    assert any(r["verdict"] == "violates" for r in out)


@pytest.mark.skipif(shutil.which("go") is None and not (Path.home() / ".local/go/bin/go").exists(),
                    reason="go is not installed")
def test_go_file_outside_a_module_is_replayed(tmp_path):
    source = tmp_path / "calc.go"
    source.write_text("package calc\n\nfunc Add(a int64, b int64) int64 {\n\treturn a + b\n}\n", encoding="utf-8")
    rows = NativeRunner().run("go", source, source.read_text(), "Add", [[1, 2]])
    assert rows == [{"ok": True, "value": 3}]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_typescript_copy_sees_the_project_node_modules(tmp_path):
    pkg = tmp_path / "node_modules" / "mumei-fake-dep"
    pkg.mkdir(parents=True)
    (pkg / "package.json").write_text('{"name": "mumei-fake-dep", "type": "module", "main": "index.js"}')
    (pkg / "index.js").write_text("export const one = 1;\n")
    (tmp_path / "package.json").write_text('{"type": "module"}')
    source = tmp_path / "calc.ts"
    source.write_text('import { one } from "mumei-fake-dep";\nfunction inc(a: number): number {\n  return a + one;\n}\n')
    assert NativeRunner().run("typescript", source, source.read_text(), "inc", [[1]]) == [{"ok": True, "value": 2}]


def test_a_dropped_port_refutation_leaves_no_counterexample(tmp_path):
    port = {"function": "clamp", "outcome": "refuted", "reason": "Postcondition violated", "body": "x",
            "counterexample": {"x": "5", "hi": "2"}}
    replayer = MagicMock()
    replayer.replay.return_value = [{"function": "clamp", "input": {"x": 5, "hi": 2}, "source": "body_port",
                                     "native": {"ok": True, "value": 2}, "verdict": "meets", "reason": ""}]
    pipeline, source = _pipeline(tmp_path, replayer, _porter(port))
    result = pipeline.audit_file(source, "python", enable_body_port=True, enable_native_replay=True)
    assert result.counterexample_values == []
