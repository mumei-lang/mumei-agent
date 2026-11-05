"""Port each audited function's body to Mumei with an LLM and verify it.

The default audit checks extracted contracts against an empty ``trusted``
body, so it never verifies what the function does. With body porting, the
LLM translates each function body as written. mumei then verifies the
translation against the extracted contract, with the file's other atoms
kept as trusted callees.

A refuted port is evidence about the translation, not about the native code:
the LLM may have changed the behaviour while translating it. The reply is
untrusted input, so it may only supply a body. It can't add declarations or
rewrite the contract.
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Literal

from agent import telemetry
from agent.audit_reporting import (
    _coerce_to_boolean_clause,
    _contract_text,
    _dict_list,
    _forge_atom_to_mumei,
    _format_params,
    _safe_identifier,
    _string_value,
)
from agent.secret_redaction import redact_secrets, redact_value

BodyPortOutcome = Literal["proven", "refuted", "inconclusive", "not_ported"]

# Native integers in these languages are 64-bit two's complement, so their
# ports are verified with mumei's fixed-width i64 arithmetic check.
FIXED_WIDTH_I64_LANGUAGES = frozenset({"go", "rust"})
CHECK_I64_OVERFLOW_FLAG = "--check-i64-overflow"
# An unsigned native integer has a different range than i64, so a function
# that uses one is verified unbounded rather than checked against i64.
# Only type positions count, since Go and Rust allow these words as names:
# a Rust type follows `:`, `->`, `<`, `[` or `&`; a Go type ends a binder.
_UNSIGNED_INT = {
    "rust": re.compile(r"(?:[:<\[&]|->)\s*(?:mut\s+)?(?:u8|u16|u32|u64|u128|usize)\b"),
    "go": re.compile(r"\b(?:uint|uint8|uint16|uint32|uint64|uintptr|byte)\s*(?=[,)\]]|$)"),
}


def _signature(native: str) -> str:
    """The function's header: its source up to the opening brace of the body."""
    return native.split("{", 1)[0]

BODY_PORT_SYSTEM_PROMPT = (
    "You translate one function into the Mumei language so that it can be checked against a fixed contract. "
    "Translate the function as it is written, including any mistakes; do not repair it and do not change "
    "the contract. A Mumei body is an expression over the parameters of the pinned atom: `let x = e;`, "
    "`if c { a } else { b }`, `while c invariant: I decreases: D { ... };`, integer arithmetic "
    "(`+ - * /`), comparisons, `&&`, `||`, `!`, `len(a)`, `a[i]` and calls to the atoms listed. "
    "There are no casts, methods, library calls or early returns; write negative literals as `(0 - 3)`. "
    'If the function can\'t be expressed this way, reply {"body": ""}. '
    'Reply with JSON only: {"body": "<the expression that goes inside body: { ... }>"}.'
)

MAX_BODY_CHARS = 8000
MAX_FUNCTION_CHARS = 12000
# The reply only fills the body; anything that declares, imports or restates
# a contract is rejected before it reaches mumei.
_FORBIDDEN = re.compile(r"\b(atom|trusted|extern|import)\b|\b(requires|ensures|body)\s*:")
_REFUTATION = re.compile(
    r"Verification Error: (Postcondition|Call to \S+: precondition|Potential |"
    r"(Loop )?[Ii]nvariant|[Tt]ermination|[Dd]ecreases|Integer arithmetic may overflow)"
)
_GO_TYPE_BRACE = re.compile(r"\b(struct|interface)\s*$")
_TS_TYPE_BRACE = re.compile(r"(:|=>|\||&|<|,)\s*$")
_RUST_CHAR = re.compile(r"'(\\[^']{1,10}|[^\\'\n])'")
_DECLARATION = {
    "go": r"^func\s+(\([^)]*\)\s*)?{n}\s*[\[(]",
    "rust": r"^\s*(pub(\([^)]*\))?\s+)?(const\s+)?(async\s+)?(unsafe\s+)?fn\s+{n}\s*[<(]",
    "typescript": r"^\s*(export\s+)?(default\s+)?(async\s+)?function\s*\*?\s*{n}\s*[<(]"
    r"|^\s*(export\s+)?(const|let)\s+{n}\s*(:[^=]*)?=\s*(async\s+)?(\([^)]*\)|\w+)\s*(:[^=]*)?=>"
    # A method declaration: a call statement would end with `;` and not with `{`.
    r"|^\s*((public|private|protected|static|async|override)\s+)*{n}\s*(<[^>]*>)?\s*\([^;]*\)\s*(:[^;]*)?\{{",
    "solidity": r"^\s*function\s+{n}\s*\(",
}


def function_source(source: str, language: str, name: str) -> str | None:
    """The text of the first function called ``name``, or None when it isn't found."""
    if language == "python":
        return _python_function_source(source, name)
    pattern = _DECLARATION.get(language)
    if pattern is None:
        return None
    # The first declaration with a body: TypeScript overload signatures and
    # Solidity interface declarations come without one.
    for match in re.finditer(pattern.format(n=re.escape(name)), source, re.MULTILINE):
        start = source.rfind("\n", 0, match.start()) + 1
        if match.group(0).endswith("=>"):
            body = len(source) - len(source[match.end():].lstrip())
            end = (
                _closing_brace(source, body)
                if source.startswith("{", body)
                else _expression_end(source, match.end())
            )
        else:
            end = _closing_brace(
                source, match.start(), rust=language == "rust", go=language == "go",
                typescript=language == "typescript",
            )
        if end is not None:
            return source[start:end]
    return None


def _expression_end(source: str, pos: int) -> int:
    """End of an arrow function's expression body: the first ``;`` or newline outside brackets."""
    depth, i, quote = 0, pos, ""
    while i < len(source):
        ch = source[i]
        if quote:
            if ch == "\\":
                i += 1
            elif ch == quote:
                quote = ""
        elif ch in "\"'`":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth < 0:
                return i
        elif ch in ";\n" and depth == 0 and source[pos:i].strip():
            return i + (ch == ";")
        i += 1
    return len(source)


def _python_function_source(source: str, name: str) -> str | None:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    lines = source.splitlines(keepends=True)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            first = min([node.lineno, *(d.lineno for d in node.decorator_list)])
            return "".join(lines[first - 1:node.end_lineno])
    return None


def _closing_brace(
    source: str, pos: int, *, rust: bool = False, go: bool = False, typescript: bool = False
) -> int | None:
    """Offset just past the brace that closes the first ``{`` at or after ``pos``.

    In Rust a ``'`` opens a char literal only when one closes it; otherwise it is a lifetime.
    In Go the braces of a ``struct{...}`` or ``interface{...}`` type in the signature are skipped,
    and in TypeScript those of an object type in the parameters or after ``:``, ``=>``, ``|`` or ``&``.
    """
    depth, parens, i, quote = 0, 0, pos, ""
    while i < len(source):
        ch = source[i]
        if quote:
            if ch == "\\":
                i += 1
            elif ch == quote:
                quote = ""
        elif source.startswith("//", i):
            nl = source.find("\n", i)
            i = len(source) if nl < 0 else nl
            continue
        elif source.startswith("/*", i):
            close = source.find("*/", i + 2)
            i = len(source) if close < 0 else close + 2
            continue
        elif ch == "'" and rust and not _RUST_CHAR.match(source, i):
            pass
        elif ch in "\"'`":
            quote = ch
        elif ch == ";" and depth == 0:
            return None
        elif ch in "()" and depth == 0 and typescript:
            parens += 1 if ch == "(" else -1
        elif ch == "{" and depth == 0 and (
            (go and _GO_TYPE_BRACE.search(source, 0, i))
            or (typescript and (parens > 0 or _TS_TYPE_BRACE.search(source, 0, i)))
        ):
            end = _closing_brace(source, i)
            if end is None:
                return None
            i = end
            continue
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return None


def ported_atom(atom: dict[str, object], body: str) -> str:
    """The atom with its extracted contract and the ported body, verified rather than trusted."""
    name = _safe_identifier(_string_value(atom.get("name"), "audited_atom"))
    params = _format_params(atom.get("params") or atom.get("inputs"))
    return_type = _string_value(atom.get("return_type"), "i64")
    requires = _coerce_to_boolean_clause(_contract_text(atom.get("requires"), "true"))
    ensures = _coerce_to_boolean_clause(_contract_text(atom.get("ensures"), "true"))
    indented = "\n".join(f"        {line}" if line.strip() else "" for line in body.strip().splitlines())
    return "\n".join(
        [
            f"atom {name}({params}) -> {return_type} {{",
            f"    requires: {requires};",
            f"    ensures: {ensures};",
            "    body: {",
            indented,
            "    }",
            "}",
        ]
    )


def parse_body(text: str) -> tuple[str | None, str]:
    """The body from an LLM reply, or None and the reason it was rejected."""
    reply = _json_object(text)
    if reply is None:
        return None, "reply is not a JSON object"
    body = reply.get("body")
    if not isinstance(body, str):
        return None, "no body in the reply"
    if not body.strip():
        return None, "the LLM could not express the function in Mumei"
    if len(body) > MAX_BODY_CHARS:
        return None, f"body is longer than {MAX_BODY_CHARS} characters"
    if _FORBIDDEN.search(body):
        return None, "body declares an atom, an import or a contract clause"
    if not _balanced(body):
        return None, "body has unbalanced brackets"
    return body, ""


def _json_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    fence = re.match(r"^```(?:json)?\s*\n(.*)\n```$", stripped, re.DOTALL)
    if fence:
        stripped = fence.group(1)
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _balanced(body: str) -> bool:
    pairs = {")": "(", "]": "[", "}": "{"}
    stack: list[str] = []
    for ch in body:
        if ch in "([{":
            stack.append(ch)
        elif ch in pairs and (not stack or stack.pop() != pairs[ch]):
            return False
    return not stack


def body_port_prompt(
    language: str, atom: dict[str, object], native: str, callees: str
) -> list[dict[str, str]]:
    header = ported_atom(atom, "...")
    user = (
        f"Language: {language}\n"
        f"Function to translate: {_string_value(atom.get('name'), '')}\n\n"
        "Atoms already defined that the body may call:\n"
        f"```\n{callees.strip() or '(none)'}\n```\n\n"
        "Pinned atom; write only what goes inside body: { ... }:\n"
        f"```\n{header}\n```\n\n"
        f"Source:\n```\n{native}\n```"
    )
    return [
        {"role": "system", "content": BODY_PORT_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def classify(verification: dict[str, object]) -> tuple[BodyPortOutcome, str, dict | None]:
    """Map a ``mumei verify`` result to an outcome, the first diagnostic and the counterexample."""
    report = verification.get("report")
    report = report if isinstance(report, dict) else {}
    raw = report.get("diagnostics")
    messages = [
        str(d.get("message") or "") if isinstance(d, dict) else d
        for d in (raw if isinstance(raw, list) else [])
        if isinstance(d, (dict, str))
    ]
    message = next((m for m in messages if m), "")
    counterexample = report.get("counterexample")
    counterexample = dict(counterexample) if isinstance(counterexample, dict) else None
    status = str(report.get("status", ""))
    if verification.get("success") and status in ("success", "verified"):
        return "proven", "", None
    if not verification.get("success") and (
        _REFUTATION.search(message) or (counterexample and status == "failed")
    ):
        return "refuted", message, counterexample
    return "inconclusive", message or status or "mumei verify returned no result", None


class BodyPorter:
    """Port and verify every atom of an extracted forge spec."""

    def __init__(self, client: Any, model: str, mumei_client: Any) -> None:
        self.client = client
        self.model = model
        self.mumei_client = mumei_client

    def port(
        self, source_code: str, language: str, forge_task_spec: dict[str, object]
    ) -> list[dict[str, object]]:
        atoms = _dict_list(forge_task_spec.get("atoms"))
        return [self._port_one(source_code, language, atom, atoms) for atom in atoms]

    def _port_one(
        self,
        source_code: str,
        language: str,
        atom: dict[str, object],
        atoms: list[dict[str, object]],
    ) -> dict[str, object]:
        name = _string_value(atom.get("name"), "")
        entry: dict[str, object] = {"function": name, "outcome": "not_ported", "reason": "", "body": ""}
        native = function_source(source_code, language, name)
        if native is None:
            entry["reason"] = "function not found in the source"
            return entry
        if len(native) > MAX_FUNCTION_CHARS:
            entry["reason"] = f"function is longer than {MAX_FUNCTION_CHARS} characters"
            return entry
        others = [a for a in atoms if a is not atom]
        prompt = body_port_prompt(language, atom, native, "\n\n".join(_forge_atom_to_mumei(a) for a in others))
        try:
            text = self._complete([{**m, "content": redact_secrets(m["content"])} for m in prompt])
        except Exception as exc:  # noqa: BLE001 - any transport failure leaves the function unported
            entry["reason"] = f"LLM request failed: {type(exc).__name__}"
            return entry
        body, reason = parse_body(text)
        if body is None:
            entry["reason"] = reason
            return entry
        # Verify redacted text, so a secret in the body or a callee's contract
        # is never written to the module file or mumei's report.
        body = redact_secrets(body)
        entry["body"] = body
        # Only the callees the body uses: another atom's extracted contract
        # may not lower, and that should not decide this port.
        callees = [_forge_atom_to_mumei(a) for a in others if _calls(body, a)]
        module = redact_secrets("\n\n".join([*callees, ported_atom(atom, body)]) + "\n")
        with tempfile.TemporaryDirectory(prefix="mumei-body-port-") as tmp:
            path = Path(tmp) / "body_port.mm"
            path.write_text(module, encoding="utf-8")
            try:
                verification, semantics = self._verify(
                    str(path), str(Path(tmp) / "report"), language, native
                )
            except (OSError, subprocess.SubprocessError) as exc:
                entry["outcome"] = "inconclusive"
                entry["reason"] = f"mumei verify failed to run: {type(exc).__name__}"
                return entry
        entry["integer_semantics"] = semantics
        outcome, message, counterexample = classify(verification)
        message = message.replace(str(path), path.name).replace(tmp, "")
        entry["outcome"] = outcome
        entry["reason"] = redact_secrets(message)
        if counterexample:
            entry["counterexample"] = redact_value(counterexample)
        return entry

    def _verify(self, path: str, report_dir: str, language: str, native: str) -> tuple[dict, str]:
        """The verification and the integer semantics it used: ``i64`` or ``unbounded``."""
        if language in FIXED_WIDTH_I64_LANGUAGES and not _UNSIGNED_INT[language].search(_signature(native)):
            verification = self.mumei_client.verify(
                path, report_dir=report_dir, extra_args=[CHECK_I64_OVERFLOW_FLAG]
            )
            stderr = str(verification.get("stderr") or "")
            # A mumei without the flag rejects the argument: verify unbounded instead.
            if not ("unexpected argument" in stderr and CHECK_I64_OVERFLOW_FLAG in stderr):
                return verification, "i64"
        return self.mumei_client.verify(path, report_dir=report_dir), "unbounded"

    def _complete(self, messages: list[dict[str, str]]) -> str:
        tracer = telemetry.get_tracer(__name__)
        with tracer.start_as_current_span("llm.body_port") as span:
            span.set_attribute("gen_ai.system", "openai-compatible")
            span.set_attribute("gen_ai.request.model", self.model)
            response = self.client.chat.completions.create(model=self.model, messages=messages)
        return response.choices[0].message.content or ""


def _calls(body: str, atom: dict[str, object]) -> bool:
    name = _safe_identifier(_string_value(atom.get("name"), ""))
    return bool(name) and re.search(rf"\b{re.escape(name)}\s*\(", body) is not None


def body_port_violations(ports: list[dict[str, object]]) -> list[str]:
    """One code finding per refuted port."""
    out = []
    for port in ports:
        if port.get("outcome") != "refuted":
            continue
        line = f"body-port: {port['function']}: the ported body does not meet the extracted contract: {port['reason']}"
        if port.get("counterexample"):
            line += f" (counterexample: {json.dumps(port['counterexample'], sort_keys=True)})"
        out.append(line)
    return out
