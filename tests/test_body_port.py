"""Tests for porting audited function bodies to Mumei and verifying them."""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agent.audit import AuditPipeline, build_parser
from agent.body_port import (
    BODY_PORT_SYSTEM_PROMPT,
    MAX_BODY_CHARS,
    BodyPorter,
    body_port_prompt,
    body_port_violations,
    classify,
    function_source,
    parse_body,
    ported_atom,
)
from agent.code_to_spec import CodeToSpecResult
from agent.config import AgentConfig
from agent.mumei_client import create_mumei_client


class ScriptedClient:
    """OpenAI-shaped client that replays one reply per request and records prompts."""

    def __init__(self, *replies: str | Exception) -> None:
        self.replies = list(replies)
        self.prompts: list[list[dict]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, *, model: str, messages: list[dict]):
        self.prompts.append(messages)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=reply))])


CLAMP = {
    "name": "clamp",
    "params": [{"name": "x", "type": "i64"}, {"name": "hi", "type": "i64"}],
    "return_type": "i64",
    "requires": "hi >= 0",
    "ensures": "result <= hi",
}


# --- function_source -------------------------------------------------------

@pytest.mark.parametrize(
    ("language", "source", "name", "expected"),
    [
        ("python", "def f(x):\n    return x\n\ndef g():\n    pass\n", "f", "def f(x):\n    return x\n"),
        ("python", "@cache\ndef f(x):\n    return x\n", "f", "@cache\ndef f(x):\n    return x\n"),
        ("python", "class A:\n    def f(self):\n        return 1\n", "f", "    def f(self):\n        return 1\n"),
        ("python", "async def f():\n    return 1\n", "f", "async def f():\n    return 1\n"),
        ("go", "package p\n\nfunc F(a int) int {\n\treturn a\n}\n", "F", "func F(a int) int {\n\treturn a\n}"),
        ("go", "func (s *S) F() int { if s.x { return 1 }; return 0 }\n", "F",
         "func (s *S) F() int { if s.x { return 1 }; return 0 }"),
        ("go", "func F[T any](a T) T {\n\treturn a\n}\n", "F", "func F[T any](a T) T {\n\treturn a\n}"),
        ("rust", "pub fn f(a: i64) -> i64 {\n    a\n}\n", "f", "pub fn f(a: i64) -> i64 {\n    a\n}"),
        ("rust", "pub(crate) const fn f<T>(a: T) -> T { a }\n", "f", "pub(crate) const fn f<T>(a: T) -> T { a }"),
        ("rust", "fn f() -> &'static str { \"}\" }\n", "f", "fn f() -> &'static str { \"}\" }"),
        ("rust", "fn f() {\n    // }\n    /* } */\n}\n", "f", "fn f() {\n    // }\n    /* } */\n}"),
        ("typescript", "export function f(a: number): number {\n  return a;\n}\n", "f",
         "export function f(a: number): number {\n  return a;\n}"),
        ("typescript", "class A {\n  public f(a: number): string {\n    return `}`;\n  }\n}\n", "f",
         "  public f(a: number): string {\n    return `}`;\n  }"),
        ("solidity", "contract C {\n    function f(uint a) public returns (uint) {\n        return a;\n    }\n}\n", "f",
         "    function f(uint a) public returns (uint) {\n        return a;\n    }"),
    ],
)
def test_function_source_finds_the_function(language, source, name, expected):
    assert function_source(source, language, name) == expected


@pytest.mark.parametrize(
    ("language", "source", "name"),
    [
        ("python", "def g():\n    pass\n", "f"),
        ("python", "def f(:\n", "f"),
        ("go", "func G() {}\n", "F"),
        ("rust", "fn fa() {}\n", "f"),
        ("rust", "trait T {\n    fn f(&self) -> i64;\n}\n", "f"),
        ("typescript", "function f(a: number): number;\n", "f"),
        ("solidity", "interface I {\n    function f() external;\n}\n", "f"),
        ("rust", "fn f() {\n    loop {\n", "f"),
        ("java", "int f() { return 1; }", "f"),
    ],
)
def test_function_source_returns_none_without_a_body(language, source, name):
    assert function_source(source, language, name) is None


# --- parse_body ------------------------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        '{"body": "if x > hi { hi } else { x }"}',
        '```json\n{"body": "x"}\n```',
        '```\n{"body": "let y = x + 1;\\ny"}\n```',
        '  {"body": "x", "note": "extra keys are ignored"}  ',
    ],
)
def test_parse_body_accepts_a_body(text):
    body, reason = parse_body(text)
    assert body and reason == ""


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("x", "not a JSON object"),
        ("[1]", "not a JSON object"),
        ('{"body": ""}', "could not express"),
        ('{"body": "   "}', "could not express"),
        ('{"body": 3}', "no body"),
        ("{}", "no body"),
        ('{"body": "' + "x" * (MAX_BODY_CHARS + 1) + '"}', "longer than"),
        ('{"body": "x } atom evil(a: i64) -> i64 { body: { a } }"}', "declares"),
        ('{"body": "trusted"}', "declares"),
        ('{"body": "extern f"}', "declares"),
        ('{"body": "import std.x; x"}', "declares"),
        ('{"body": "x; requires: true"}', "declares"),
        ('{"body": "x; ensures : true"}', "declares"),
        ('{"body": "x } body: { 0"}', "declares"),
        ('{"body": "x }"}', "unbalanced"),
        ('{"body": "(x"}', "unbalanced"),
        ('{"body": "a[0)"}', "unbalanced"),
    ],
)
def test_parse_body_rejects_untrusted_replies(text, reason):
    body, why = parse_body(text)
    assert body is None and reason in why


def test_identifiers_that_contain_keywords_are_not_rejected():
    body, _ = parse_body('{"body": "let body_len = atoms + imported; body_len"}')
    assert body is not None


# --- ported_atom / prompt --------------------------------------------------

def test_ported_atom_is_verified_and_keeps_the_extracted_contract():
    text = ported_atom(CLAMP, "let y = x;\ny")
    assert text.startswith("atom clamp(x: i64, hi: i64) -> i64 {")
    assert "trusted" not in text
    assert "    requires: hi >= 0;" in text and "    ensures: result <= hi;" in text
    assert "        let y = x;\n        y\n    }\n}" in text


def test_prompt_carries_only_the_function_and_the_callees():
    messages = body_port_prompt("go", CLAMP, "func clamp(x, hi int) int { return x }", "trusted atom h() -> i64 {}")
    assert messages[0] == {"role": "system", "content": BODY_PORT_SYSTEM_PROMPT}
    user = messages[1]["content"]
    assert "func clamp(x, hi int) int { return x }" in user
    assert "trusted atom h() -> i64 {}" in user
    assert "requires: hi >= 0;" in user


def test_prompt_says_none_without_callees():
    assert "(none)" in body_port_prompt("go", CLAMP, "func clamp() {}", "")[1]["content"]


# --- classify --------------------------------------------------------------

def _diag(message):
    return [{"message": message}]


@pytest.mark.parametrize(
    ("verification", "outcome"),
    [
        ({"success": True, "report": {"status": "success"}}, "proven"),
        ({"success": True, "report": {"status": "verified"}}, "proven"),
        ({"success": True, "report": {"status": "trusted"}}, "inconclusive"),
        ({"success": True, "report": {"status": "satisfiable_with_skips"}}, "inconclusive"),
        ({"success": False, "report": {"status": "failed", "diagnostics": _diag(
            "Verification Error: Postcondition (ensures) is not satisfied.")}}, "refuted"),
        ({"success": False, "report": {"status": "failed", "diagnostics": _diag(
            "Verification Error: Call to helper: precondition not satisfied")}}, "refuted"),
        ({"success": False, "report": {"status": "failed", "diagnostics": _diag(
            "Verification Error: Potential division by zero")}}, "refuted"),
        ({"success": False, "report": {"status": "failed", "diagnostics": _diag(
            "Verification Error: Loop invariant does not hold on entry")}}, "refuted"),
        ({"success": False, "report": {"status": "failed", "counterexample": {"x": "1"}}}, "refuted"),
        ({"success": False, "report": {"status": "failed", "diagnostics": _diag(
            "Syntax error(s) in 'body_port.mm'")}}, "inconclusive"),
        ({"success": False, "report": {"status": "failed", "diagnostics": _diag(
            "Unknown function: helper")}}, "inconclusive"),
        ({"success": False, "report": {}}, "inconclusive"),
        ({"success": False}, "inconclusive"),
        ({"success": False, "report": "not a dict"}, "inconclusive"),
    ],
)
def test_classify(verification, outcome):
    assert classify(verification)[0] == outcome


def test_classify_returns_the_counterexample_of_a_refutation():
    outcome, message, ce = classify({"success": False, "report": {
        "status": "failed", "counterexample": {"x": "-1"},
        "diagnostics": _diag("Verification Error: Postcondition (ensures) is not satisfied.")}})
    assert (outcome, ce) == ("refuted", {"x": "-1"})
    assert message.startswith("Verification Error: Postcondition")


# --- BodyPorter with a stub mumei -------------------------------------------

def _stub_mumei(verification):
    mumei = MagicMock()
    mumei.verify.return_value = verification
    return mumei


GO_CLAMP = "func clamp(x int64, hi int64) int64 {\n\tif x > hi {\n\t\treturn hi\n\t}\n\treturn x\n}\n"


def test_porter_records_a_function_missing_from_the_source():
    porter = BodyPorter(ScriptedClient(), "m", _stub_mumei({}))
    (entry,) = porter.port("func other() {}\n", "go", {"atoms": [CLAMP]})
    assert entry["outcome"] == "not_ported" and "not found" in entry["reason"]


def test_porter_records_a_failed_request_without_the_exception_text():
    porter = BodyPorter(ScriptedClient(RuntimeError("secret-ish detail")), "m", _stub_mumei({}))
    (entry,) = porter.port(GO_CLAMP, "go", {"atoms": [CLAMP]})
    assert entry["outcome"] == "not_ported"
    assert entry["reason"] == "LLM request failed: RuntimeError"


def test_porter_does_not_verify_a_rejected_reply():
    mumei = _stub_mumei({})
    porter = BodyPorter(ScriptedClient('{"body": "0 } trusted atom x() -> i64 { body: { 0 } }"}'), "m", mumei)
    (entry,) = porter.port(GO_CLAMP, "go", {"atoms": [CLAMP]})
    assert entry["outcome"] == "not_ported" and "declares" in entry["reason"]
    mumei.verify.assert_not_called()


def _recording_mumei(verification):
    mumei, seen = MagicMock(), []

    def verify(path, report_dir=None):
        seen.append(Path(path).read_text())
        return verification

    mumei.verify.side_effect = verify
    return mumei, seen


HELPER = {"name": "helper", "params": [], "return_type": "i64", "requires": "true", "ensures": "result >= 0"}
BROKEN = {"name": "broken", "params": [{"name": "xs", "type": "[]Movement"}], "return_type": "i64"}


def test_porter_keeps_the_atoms_the_body_calls_as_trusted_callees():
    mumei, seen = _recording_mumei({"success": True, "report": {"status": "success"}})
    client = ScriptedClient('{"body": "if helper() > hi { hi } else { x }"}', '{"body": "0"}', '{"body": "0"}')
    source = GO_CLAMP + "func helper() int64 { return 0 }\nfunc broken() int64 { return 0 }\n"
    entries = BodyPorter(client, "m", mumei).port(source, "go", {"atoms": [CLAMP, HELPER, BROKEN]})
    assert [e["outcome"] for e in entries] == ["proven", "proven", "proven"]
    assert seen[0].startswith("trusted atom helper() -> i64 {")
    assert "\natom clamp(x: i64, hi: i64) -> i64 {" in seen[0]
    assert "broken" not in seen[0]
    assert seen[1].startswith("atom helper() -> i64 {")
    # Every other atom is offered to the LLM, even those the body ends up not calling.
    assert "trusted atom broken(" in client.prompts[0][1]["content"]


def test_a_name_that_only_contains_a_callee_is_not_a_call():
    mumei, seen = _recording_mumei({"success": True, "report": {"status": "success"}})
    client = ScriptedClient('{"body": "let helper_x = x; helper_x"}')
    BodyPorter(client, "m", mumei).port(GO_CLAMP, "go", {"atoms": [CLAMP, HELPER]})
    assert "helper()" not in seen[0]


def test_reasons_do_not_carry_the_temporary_path():
    mumei, seen = MagicMock(), []

    def verify(path, report_dir=None):
        seen.append(path)
        return {"success": False, "report": {"status": "failed", "diagnostics": _diag(
            f"Syntax error(s) in atom bodies of '{path}': unexpected token")}}

    mumei.verify.side_effect = verify
    (entry,) = BodyPorter(ScriptedClient('{"body": "x"}'), "m", mumei).port(GO_CLAMP, "go", {"atoms": [CLAMP]})
    assert entry["outcome"] == "inconclusive"
    assert str(Path(seen[0]).parent) not in entry["reason"]
    assert "'body_port.mm'" in entry["reason"]


def test_porter_does_not_send_the_rest_of_the_file():
    client = ScriptedClient('{"body": "x"}')
    source = GO_CLAMP + "func unrelated() string { return \"do-not-send\" }\n"
    BodyPorter(client, "m", _stub_mumei({"success": True, "report": {"status": "success"}})).port(
        source, "go", {"atoms": [CLAMP]})
    assert "do-not-send" not in client.prompts[0][1]["content"]


def test_violations_list_only_refuted_ports():
    ports = [
        {"function": "a", "outcome": "proven", "reason": ""},
        {"function": "b", "outcome": "refuted", "reason": "Verification Error: Postcondition", "counterexample": {"x": "1"}},
        {"function": "c", "outcome": "refuted", "reason": "Verification Error: Potential division by zero"},
        {"function": "d", "outcome": "inconclusive", "reason": "Syntax error"},
        {"function": "e", "outcome": "not_ported", "reason": "no body"},
    ]
    assert body_port_violations(ports) == [
        (
            "body-port: b: the ported body does not meet the extracted contract: Verification Error: Postcondition"
            ' (counterexample: {"x": "1"})'
        ),
        "body-port: c: the ported body does not meet the extracted contract: Verification Error: Potential division by zero",
    ]


# --- BodyPorter with the real mumei -------------------------------------------

MUMEI = os.environ.get("MUMEI_BIN") or shutil.which("mumei")
needs_mumei = pytest.mark.skipif(not MUMEI, reason="mumei binary not available")


@needs_mumei
@pytest.mark.parametrize(
    ("reply", "outcome"),
    [
        ('{"body": "if x > hi { hi } else { x }"}', "proven"),
        ('{"body": "x"}', "refuted"),
        ('{"body": "if x > hi { hi } else { x + 1 }"}', "refuted"),
        ('{"body": "x +"}', "inconclusive"),
    ],
)
def test_porter_verifies_with_mumei(reply, outcome):
    porter = BodyPorter(ScriptedClient(reply), "m", create_mumei_client(MUMEI))
    (entry,) = porter.port(GO_CLAMP, "go", {"atoms": [CLAMP]})
    assert entry["outcome"] == outcome, entry
    if outcome == "refuted":
        assert entry["counterexample"]


# --- AuditPipeline wiring --------------------------------------------------

def _pipeline(tmp_path, *, porter=None, client=None, config=None):
    source = tmp_path / "clamp.go"
    source.write_text(GO_CLAMP, encoding="utf-8")
    extractor = MagicMock()
    extractor.extract_from_file.return_value = CodeToSpecResult(
        success=True, natural_language_spec="clamp x to hi", forge_task_spec={"atoms": [CLAMP]},
        detected_language="go")
    foreign = MagicMock()
    foreign.verify.return_value = {"success": True, "verification": {"success": True, "report": {"status": "verified"}}}
    cross = MagicMock()
    cross.validate_spec_vs_impl.return_value = MagicMock(gaps=[], issues=[])
    pipeline = AuditPipeline(
        config or AgentConfig(api_key=""), code_to_spec_extractor=extractor, foreign_code_verifier=foreign,
        cross_validator=cross, mumei_client=MagicMock(), spec_health_checker=MagicMock(),
        body_porter=porter, client=client)
    return pipeline, source


def _porter(*entries):
    porter = MagicMock()
    porter.port.return_value = list(entries)
    return porter


REFUTED = {"function": "clamp", "outcome": "refuted", "reason": "Verification Error: Postcondition",
           "body": "x", "counterexample": {"x": "1", "hi": "0"}}


def test_body_port_is_off_by_default(tmp_path):
    porter = _porter(REFUTED)
    pipeline, source = _pipeline(tmp_path, porter=porter)
    result = pipeline.audit_file(source, "go")
    porter.port.assert_not_called()
    assert result.body_ports == []


def test_a_refuted_port_is_a_code_finding(tmp_path):
    pipeline, source = _pipeline(tmp_path, porter=_porter(REFUTED))
    result = pipeline.audit_file(source, "go", enable_body_port=True)
    assert result.body_ports == [REFUTED]
    assert result.success is False
    assert result.verification_status == "refuted"
    assert any(v.startswith("body-port: clamp:") for v in result.verification_violations)
    assert {"function_name": "clamp", "counterexample": {"x": "1", "hi": "0"}} in result.counterexample_values


@pytest.mark.parametrize("outcome", ["proven", "inconclusive", "not_ported"])
def test_other_outcomes_are_recorded_without_a_finding(tmp_path, outcome):
    entry = {"function": "clamp", "outcome": outcome, "reason": "", "body": ""}
    pipeline, source = _pipeline(tmp_path, porter=_porter(entry))
    result = pipeline.audit_file(source, "go", enable_body_port=True)
    assert result.body_ports == [entry]
    assert not any(v.startswith("body-port:") for v in result.verification_violations)


def test_without_an_llm_the_port_is_skipped_with_a_reason(tmp_path):
    pipeline, source = _pipeline(tmp_path)
    result = pipeline.audit_file(source, "go", enable_body_port=True)
    (entry,) = result.body_ports
    assert entry["outcome"] == "not_ported" and "LLM_API_KEY" in entry["reason"]
    assert not any(v.startswith("body-port:") for v in result.verification_violations)


def test_the_injected_client_is_used_for_porting(tmp_path):
    client = ScriptedClient('{"body": "x"}')
    pipeline, source = _pipeline(tmp_path, client=client)
    pipeline.mumei_client.verify.return_value = {"success": True, "report": {"status": "success"}}
    result = pipeline.audit_file(source, "go", enable_body_port=True)
    assert [p["outcome"] for p in result.body_ports] == ["proven"]
    assert len(client.prompts) == 1


def test_directory_audits_pass_the_option_through(tmp_path):
    porter = _porter(REFUTED)
    pipeline, _ = _pipeline(tmp_path, porter=porter)
    result = pipeline.audit_file(tmp_path, "go", enable_body_port=True)
    porter.port.assert_called_once()
    assert result.file_results[0].body_ports == [REFUTED]


@pytest.mark.parametrize(("argv", "expected"), [([], False), (["--enable-body-port"], True)])
def test_cli_flag(argv, expected):
    args = build_parser().parse_args(["--code-file", "x.go", *argv])
    assert args.enable_body_port is expected


@pytest.mark.parametrize(
    "source",
    [
        "fn f<'a>(s: &'a str) -> char { if s.is_empty() { '}' } else { '\\n' } }\n",
        "fn f() -> char { '\\u{7d}' }\n",
    ],
)
def test_rust_lifetimes_and_char_literals(source):
    assert function_source(source, "rust", "f") == source.rstrip("\n")


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("export const f = (a: number): number => {\n  return a;\n};\n",
         "export const f = (a: number): number => {\n  return a;\n}"),
        ("const f = async x => {\n  return x;\n};\n", "const f = async x => {\n  return x;\n}"),
        ("class A {\n  g() {\n    f(1);\n  }\n  f(a: number) {\n    return a;\n  }\n}\n",
         "  f(a: number) {\n    return a;\n  }"),
        ("class A {\n  async f<T>(a: T): Promise<T> {\n    return a;\n  }\n}\n",
         "  async f<T>(a: T): Promise<T> {\n    return a;\n  }"),
    ],
)
def test_typescript_arrow_functions_and_methods(source, expected):
    assert function_source(source, "typescript", "f") == expected


def test_typescript_call_statements_are_not_declarations():
    assert function_source("function g() {\n  f(1);\n}\n", "typescript", "f") is None


@pytest.mark.parametrize("exc", [FileNotFoundError("mumei"), PermissionError("mumei")])
def test_a_verifier_that_cannot_run_leaves_the_port_inconclusive(exc):
    mumei = MagicMock()
    mumei.verify.side_effect = exc
    (entry,) = BodyPorter(ScriptedClient('{"body": "x"}'), "m", mumei).port(GO_CLAMP, "go", {"atoms": [CLAMP]})
    assert entry["outcome"] == "inconclusive"
    assert entry["reason"] == f"mumei verify failed to run: {type(exc).__name__}"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("const f = (x: number) => x + 1;\nconst g = 2;\n", "const f = (x: number) => x + 1;"),
        ("export const f = (x) => g(x,\n  1)\nconst h = 3\n", "export const f = (x) => g(x,\n  1)"),
        ("const f = x =>\n  x * 2;\n", "const f = x =>\n  x * 2;"),
    ],
)
def test_typescript_expression_bodied_arrows(source, expected):
    assert function_source(source, "typescript", "f") == expected


def test_typescript_overloads_resolve_to_the_implementation():
    source = (
        "function f(a: string): string;\n"
        "function f(a: number): number;\n"
        "function f(a: any): any {\n  return a;\n}\n"
    )
    assert function_source(source, "typescript", "f") == "function f(a: any): any {\n  return a;\n}"


@pytest.mark.parametrize(
    "signature",
    [
        "func f(a int) struct{ ok bool } {",
        "func f(a int) (struct{ v struct{ n int } }, error) {",
        "func f[T interface{ ~int }](a T) T {",
        "func f(a interface{}) interface {\n\tM()\n} {",
    ],
)
def test_go_signature_type_braces_are_not_the_body(signature):
    source = f"{signature}\n\treturn a\n}}\n\nfunc g() {{}}\n"
    assert function_source(source, "go", "f") == f"{signature}\n\treturn a\n}}"


@pytest.mark.parametrize(
    ("diagnostics", "outcome"),
    [
        (["Verification Error: Postcondition (ensures) is not satisfied"], "refuted"),
        (["", "Verification Error: Potential division by zero"], "refuted"),
        (["Unknown function: foo"], "inconclusive"),
        ([42, None], "inconclusive"),
    ],
)
def test_string_diagnostics_are_classified(diagnostics, outcome):
    got, _, _ = classify({"success": False, "report": {"status": "failed", "diagnostics": diagnostics}})
    assert got == outcome


def test_reports_list_body_ports():
    from agent.audit_models import AuditResult
    from agent.audit_reporting import _build_markdown_report, _build_report

    result = AuditResult(source_file="a.go", language="go", success=False, spec_extracted=True)
    result.body_ports = [
        {"function": "clamp", "outcome": "proven", "reason": ""},
        {"function": "split", "outcome": "not_ported", "reason": "the LLM could not express the function in Mumei"},
    ]
    text = _build_report(result)
    assert "  - clamp: proven\n" in text
    assert "  - split: not_ported (the LLM could not express the function in Mumei)" in text
    md = _build_markdown_report(result)
    assert "split: not_ported" in md
    assert "clamp: proven" not in md


@pytest.mark.parametrize(
    "signature",
    [
        "function f(a: { x: number }): { y: number } {",
        "export function f(a: number): Promise<{ ok: boolean }> {",
        "function f(a: number): { a: 1 } | { b: 2 } {",
        "function f(\n  a: { x: number },\n  b: number,\n): number {",
    ],
)
def test_typescript_object_types_are_not_the_body(signature):
    source = f"{signature}\n  return a;\n}}\n\nfunction g() {{}}\n"
    assert function_source(source, "typescript", "f") == f"{signature}\n  return a;\n}}"


@pytest.mark.parametrize(
    "signature",
    [
        "  f(): () => number {",
        "  f(a: { x: number }): number {",
        "  public f(\n    a: number,\n  ): (b: number) => { c: number } {",
    ],
)
def test_typescript_methods_with_function_and_object_types(signature):
    source = f"class A {{\n{signature}\n    return a;\n  }}\n}}\n"
    assert function_source(source, "typescript", "f") == f"{signature}\n    return a;\n  }}"


def test_typescript_callback_calls_are_not_method_declarations():
    assert function_source("function g() {\n  f(x).then(() => {\n    h();\n  });\n}\n", "typescript", "f") is None
