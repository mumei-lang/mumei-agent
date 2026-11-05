"""Run audited functions natively and check the extracted contract on what they return.

A counterexample from mumei is a claim about the Mumei model of a function. The
model can be wrong: a body port may change the behaviour and the empty
``trusted`` body says nothing about it. Native replay calls the real function
on the counterexample (and on a few boundary inputs), pins the inputs and the
returned value into a Mumei atom with the extracted contract, and lets mumei
decide whether the native result violates the contract. Only that is a
confirmed finding.

Replay executes the audited code on this machine, so it is opt-in
(``audit --enable-native-replay``). Inputs and results are restricted to
integers, booleans and integer arrays, and the harnesses are generated from
fixed templates: nothing from an LLM reply or a counterexample is executed as
code.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from agent.audit_reporting import (
    _coerce_to_boolean_clause,
    _contract_text,
    _dict_list,
    _forge_atom_to_mumei,
    _safe_identifier,
    _string_value,
)
from agent.body_port import _calls, classify, function_source
from agent.secret_redaction import REDACTED, redact_secrets, redact_value

ReplayVerdict = Literal[
    "violates", "meets", "outside_requires", "raised", "unexpressible", "unsupported", "inconclusive"
]
InputSource = Literal["body_port", "counterexample", "boundary"]

MAX_INPUTS_PER_FUNCTION = 12
MAX_ARRAY_LEN = 64
NATIVE_TIMEOUT = 120
BUILD_TIMEOUT = 600
MARK = "\x1emumei-native-replay\x1e"
_RUST_MARK = '"\\u{1e}mumei-native-replay\\u{1e}"'

_INT_TYPE = re.compile(r"^(i|u)(8|16|32|64|128|size)$")
_REQUIRES_CONTRADICTION = re.compile(r"Spec contradiction in atom '[^']*': requires|^requires_unsat\b")
_Z3_NEG = re.compile(r"^\(\s*-\s*(\d+)\s*\)$")
_BOUNDARY_INTS = (0, 1, -1, 2, 7, 100, -100)
SUPPORTED_LANGUAGES = ("python", "typescript", "go", "rust")


@dataclass(frozen=True)
class Param:
    name: str
    kind: Literal["int", "bool", "int_array"]


class Unexpressible(ValueError):
    """An input or result that the harness or the contract check can't represent."""


def _kind(mumei_type: str) -> Literal["int", "bool", "int_array"] | None:
    t = mumei_type.replace(" ", "")
    if t == "bool":
        return "bool"
    if _INT_TYPE.match(t):
        return "int"
    if t.startswith("[") and t.endswith("]") and _INT_TYPE.match(t[1:-1]):
        return "int_array"
    return None


def atom_params(atom: dict[str, object]) -> list[Param] | None:
    """The atom's parameters, or None when one has a type replay can't build."""
    params = []
    for item in _dict_list(atom.get("params") or atom.get("inputs")):
        kind = _kind(_string_value(item.get("type"), "i64"))
        if kind is None:
            return None
        params.append(Param(_safe_identifier(_string_value(item.get("name"), "arg")), kind))
    return params


def coerce_value(raw: object, kind: str) -> object:
    """A counterexample value as a Python int, bool or list of ints."""
    if kind == "bool":
        if isinstance(raw, bool):
            return raw
        text = str(raw).strip().lower()
        if text in ("true", "false"):
            return text == "true"
        raise Unexpressible("value is not a boolean")
    if kind == "int_array":
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise Unexpressible("array value is not a JSON list") from exc
        if not isinstance(raw, list) or len(raw) > MAX_ARRAY_LEN:
            raise Unexpressible(f"array value is not a list of at most {MAX_ARRAY_LEN} integers")
        return [coerce_value(x, "int") for x in raw]
    if isinstance(raw, bool):
        raise Unexpressible("value is not an integer")
    if isinstance(raw, int):
        return raw
    text = str(raw).strip().replace("_", "")
    neg = _Z3_NEG.match(text)
    if neg:
        return -int(neg.group(1))
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    raise Unexpressible("value is not an integer")


def counterexample_input(params: list[Param], counterexample: dict[str, object]) -> dict[str, object]:
    """The values for every parameter; ones the model left free get a default."""
    values: dict[str, object] = {}
    for p in params:
        if p.name in counterexample:
            values[p.name] = coerce_value(counterexample[p.name], p.kind)
        else:
            values[p.name] = False if p.kind == "bool" else [] if p.kind == "int_array" else 0
    return values


def boundary_inputs(params: list[Param], limit: int = MAX_INPUTS_PER_FUNCTION) -> list[dict[str, object]]:
    """Zero, one, minus one and a few more: each parameter varied with the others at zero."""
    choices = {
        "int": list(_BOUNDARY_INTS),
        "bool": [False, True],
        "int_array": [[], [0], [1, -1], [5, 3, 9]],
    }
    base = {p.name: choices[p.kind][0] for p in params}
    out: list[dict[str, object]] = [dict(base)]
    if params:
        out.append({p.name: choices[p.kind][1] for p in params})
    for p in params:
        for value in choices[p.kind][1:]:
            out.append({**base, p.name: value})
    unique: list[dict[str, object]] = []
    for values in out:
        if values not in unique:
            unique.append(values)
    return unique[:limit]


def mm_literal(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value) if value >= 0 else f"(0 - {-value})"
    raise Unexpressible(f"{type(value).__name__} result")


def pin_clause(params: list[Param], values: dict[str, object]) -> str:
    clauses: list[str] = []
    for p in params:
        v = values[p.name]
        if p.kind == "bool":
            clauses.append(p.name if v else f"!{p.name}")
        elif p.kind == "int_array":
            assert isinstance(v, list)
            clauses.append(f"len({p.name}) == {len(v)}")
            clauses.extend(f"{p.name}[{i}] == {mm_literal(x)}" for i, x in enumerate(v))
        else:
            clauses.append(f"{p.name} == {mm_literal(v)}")
    return " && ".join(clauses) or "true"


def contract_check_module(
    atom: dict[str, object],
    params: list[Param],
    values: dict[str, object],
    result: object,
    others: list[dict[str, object]],
    *,
    check_ensures: bool = True,
) -> str:
    """An atom whose body is the native result, with the inputs pinned in ``requires``."""
    name = _safe_identifier(_string_value(atom.get("name"), "audited_atom"))
    signature = ", ".join(
        f"{_safe_identifier(_string_value(i.get('name'), 'arg'))}: {_string_value(i.get('type'), 'i64')}"
        for i in _dict_list(atom.get("params") or atom.get("inputs"))
    )
    return_type = _string_value(atom.get("return_type"), "i64")
    requires = _coerce_to_boolean_clause(_contract_text(atom.get("requires"), "true"))
    ensures = _coerce_to_boolean_clause(_contract_text(atom.get("ensures"), "true")) if check_ensures else "true"
    clauses = f"{requires} {ensures}"
    callees = [_forge_atom_to_mumei(a) for a in others if _calls(clauses, a)]
    atom_text = "\n".join(
        [
            f"atom {name}({signature}) -> {return_type} {{",
            f"    requires: ({requires}) && {pin_clause(params, values)};",
            f"    ensures: {ensures};",
            "    body: {",
            f"        {mm_literal(result)}",
            "    }",
            "}",
        ]
    )
    return "\n\n".join([*callees, atom_text]) + "\n"


def _int_range(native_type: str) -> tuple[int, int] | None:
    m = re.fullmatch(r"(u?)int(8|16|32|64)?|(i|u)(8|16|32|64|128|size)|(byte|rune|uintptr)", native_type)
    if not m:
        return None
    if m.group(5):
        bits = {"byte": 8, "rune": 32, "uintptr": 64}[m.group(5)]
        signed = m.group(5) == "rune"
    elif m.group(3):
        signed = m.group(3) == "i"
        bits = 64 if m.group(4) == "size" else int(m.group(4))
    else:
        signed = not m.group(1)
        bits = int(m.group(2) or 64)
    return (-(1 << (bits - 1)), (1 << (bits - 1)) - 1) if signed else (0, (1 << bits) - 1)


def _split_top(text: str) -> list[str]:
    parts, depth, cur = [], 0, ""
    for ch in text:
        if ch in "([{<":
            depth += 1
        elif ch in ")]}>":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur.strip())
    return parts


def _paren_group(text: str, start: int) -> tuple[str, int] | None:
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[start + 1:i], i + 1
    return None


def go_signature(func_source: str) -> tuple[list[str], list[str]] | None:
    """(parameter types, result types) of a plain Go function; None for methods."""
    head = func_source.lstrip()
    if not head.startswith("func ") or re.match(r"func\s*\(", head):
        return None
    group = _paren_group(head, head.index("("))
    if group is None:
        return None
    params_text, end = group
    types: list[str] = []
    pending = 0
    for part in _split_top(params_text):
        bits = part.split(None, 1)
        if len(bits) == 1:
            pending += 1
            continue
        types.extend([bits[1].strip()] * (pending + 1))
        pending = 0
    if pending:
        return None
    rest = head[end:head.index("{", end)].strip()
    if rest.startswith("("):
        results = [r.split()[-1] for r in _split_top(rest[1:-1])]
    else:
        results = [rest] if rest else []
    return types, results


def rust_signature(func_source: str) -> list[str] | None:
    """Parameter types of a free Rust function; None for methods and generics."""
    m = re.search(r"\bfn\s+\w+\s*\(", func_source)
    if m is None:
        return None
    group = _paren_group(func_source, m.end() - 1)
    if group is None:
        return None
    types = []
    for part in _split_top(group[0]):
        if "self" in part.split(":")[0] or ":" not in part:
            return None
        types.append(part.split(":", 1)[1].strip())
    return types


def _go_literal(value: object, native_type: str) -> str:
    if isinstance(value, bool):
        if native_type != "bool":
            raise Unexpressible(f"bool for Go {native_type}")
        return "true" if value else "false"
    if isinstance(value, list):
        if not native_type.startswith("[]"):
            raise Unexpressible(f"array for Go {native_type}")
        elem = native_type[2:]
        return f"{native_type}{{{', '.join(_go_literal(v, elem) for v in value)}}}"
    bounds = _int_range(native_type)
    if bounds is None or not bounds[0] <= int(value) <= bounds[1]:
        raise Unexpressible(f"{value} for Go {native_type}")
    return f"{native_type}({value})"


def _rust_literal(value: object, native_type: str) -> str:
    t = native_type.replace(" ", "")
    if isinstance(value, bool):
        if t != "bool":
            raise Unexpressible(f"bool for Rust {native_type}")
        return "true" if value else "false"
    if isinstance(value, list):
        m = re.fullmatch(r"(&(?:mut)?)?(?:\[(\w+)\]|Vec<(\w+)>)", t)
        if m is None:
            raise Unexpressible(f"array for Rust {native_type}")
        elem = m.group(2) or m.group(3)
        items = ", ".join(_rust_literal(v, elem) for v in value)
        body = f"vec![{items}]" if m.group(3) else f"[{items}][..]"
        if not m.group(1):
            return f"vec![{items}]"
        return f"{'&mut ' if 'mut' in m.group(1) else '&'}{body}"
    bounds = _int_range(t)
    if bounds is None or not bounds[0] <= int(value) <= bounds[1]:
        raise Unexpressible(f"{value} for Rust {native_type}")
    return f"({value}{t})" if int(value) < 0 else f"{value}{t}"


_ERROR_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.]{0,63}|unreadable harness output")


def _parse_marked(stdout: str) -> list[dict[str, Any]]:
    rows = []
    # Not splitlines(): it also splits on the record separator in MARK.
    for line in stdout.split("\n"):
        idx = line.find(MARK)
        if idx >= 0:
            try:
                row = json.loads(line[idx + len(MARK):])
            except json.JSONDecodeError:
                row = {"ok": False, "error": "unreadable harness output"}
            if isinstance(row, dict) and not row.get("ok", False):
                # Keep only a type name: otherwise the audited code picks the text.
                error = row.get("error")
                row["error"] = error if isinstance(error, str) and _ERROR_NAME.fullmatch(error) else "exception"
            rows.append(row)
    return rows


_PY_DRIVER = r'''
import importlib.util, json, os, sys
MARK = "\x1emumei-native-replay\x1e"
path, name = sys.argv[1], sys.argv[2]
sys.path.insert(0, os.path.dirname(path))
spec = importlib.util.spec_from_file_location("mumei_native_replay_target", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
fn = getattr(module, name)
for line in sys.stdin:
    if not line.strip():
        continue
    try:
        value = fn(*json.loads(line))
    except Exception as exc:
        row = {"ok": False, "error": type(exc).__name__}
    else:
        row = {"ok": True, "value": value} if isinstance(value, (bool, int)) else {"ok": True, "type": type(value).__name__}
    print(MARK + json.dumps(row), flush=True)
'''

_TS_DRIVER = r'''
import { createInterface } from "node:readline";
import { pathToFileURL } from "node:url";
const MARK = "\x1emumei-native-replay\x1e";
const mod = await import(pathToFileURL(process.argv[2]).href);
const fn = mod.__mumeiNativeReplayTarget;
for await (const line of createInterface({ input: process.stdin })) {
  if (!line.trim()) continue;
  let row;
  try {
    const value = fn(...JSON.parse(line));
    if (typeof value === "boolean" || (typeof value === "number" && Number.isSafeInteger(value))) row = { ok: true, value };
    else if (typeof value === "bigint") row = { ok: true, value: value.toString(), bigint: true };
    else row = { ok: true, type: typeof value };
  } catch (e) {
    row = { ok: false, error: e?.name ?? "Error" };
  }
  console.log(MARK + JSON.stringify(row));
}
'''

_IGNORE = shutil.ignore_patterns(".git", "node_modules", "target", "__pycache__", ".venv", "dist", "out")


def _find_up(start: Path, marker: str) -> Path | None:
    for d in [start, *start.parents]:
        if (d / marker).exists():
            return d
    return None


def _go_bin() -> str | None:
    found = shutil.which("go")
    fallback = Path.home() / ".local" / "go" / "bin" / "go"
    return found or (str(fallback) if fallback.exists() else None)


class NativeRunner:
    """Call one function of a source file on a batch of argument lists."""

    def __init__(self) -> None:
        self._cargo_target: tempfile.TemporaryDirectory[str] | None = None

    def _cargo_env(self) -> dict[str, str]:
        # One target directory per runner, so the crate's dependencies build once per audit.
        if self._cargo_target is None:
            self._cargo_target = tempfile.TemporaryDirectory(prefix="mumei-native-replay-target-")
        return {**os.environ, "CARGO_TARGET_DIR": self._cargo_target.name}

    def run(
        self, language: str, source_path: Path, source_code: str, function: str, calls: list[list[object]]
    ) -> list[dict[str, Any]]:
        """One ``{"ok", "value" | "type" | "error"}`` row per call; raises Unexpressible or RuntimeError."""
        if not calls:
            return []
        func = function_source(source_code, language, function)
        if func is None:
            raise Unexpressible("function not found in the source")
        if language == "python":
            return self._python(source_path, function, calls)
        if language == "typescript":
            return self._typescript(source_path, function, calls)
        if language == "go":
            return self._go(source_path, source_code, func, function, calls)
        if language == "rust":
            return self._rust(source_path, func, function, calls)
        raise Unexpressible(f"native replay does not support {language}")

    @staticmethod
    def _rows(proc: subprocess.CompletedProcess[str], calls: list[list[object]], what: str) -> list[dict[str, Any]]:
        rows = _parse_marked(proc.stdout)
        if len(rows) != len(calls):
            raise RuntimeError(f"{what} gave {len(rows)} of {len(calls)} results (exit {proc.returncode})")
        return rows

    def _python(self, source_path: Path, function: str, calls: list[list[object]]) -> list[dict[str, Any]]:
        stdin = "".join(json.dumps(c) + "\n" for c in calls)
        proc = subprocess.run(
            [sys.executable, "-c", _PY_DRIVER, str(source_path), function],
            input=stdin, capture_output=True, text=True, cwd=source_path.parent, timeout=NATIVE_TIMEOUT,
        )
        return self._rows(proc, calls, "the Python harness")

    def _typescript(self, source_path: Path, function: str, calls: list[list[object]]) -> list[dict[str, Any]]:
        if shutil.which("node") is None:
            raise Unexpressible("node is not installed")
        with tempfile.TemporaryDirectory(prefix="mumei-native-replay-") as tmp:
            work = Path(tmp) / "src"
            shutil.copytree(source_path.parent, work, ignore=_IGNORE)
            modules = _find_up(source_path.parent, "node_modules")
            if modules is not None:
                # Node looks for packages in the parent directories of the copy.
                (Path(tmp) / "node_modules").symlink_to(modules / "node_modules", target_is_directory=True)
            target = work / source_path.name
            target.write_text(
                target.read_text(encoding="utf-8") + f"\nexport {{ {function} as __mumeiNativeReplayTarget }};\n",
                encoding="utf-8",
            )
            driver = Path(tmp) / "driver.mjs"
            driver.write_text(_TS_DRIVER, encoding="utf-8")
            proc = subprocess.run(
                ["node", "--no-warnings", str(driver), str(target)],
                input="".join(json.dumps(c) + "\n" for c in calls),
                capture_output=True, text=True, cwd=work, timeout=NATIVE_TIMEOUT,
            )
        return self._rows(proc, calls, "the TypeScript harness")

    def _go(
        self, source_path: Path, source_code: str, func: str, function: str, calls: list[list[object]]
    ) -> list[dict[str, Any]]:
        go = _go_bin()
        if go is None:
            raise Unexpressible("go is not installed")
        signature = go_signature(func)
        package = re.search(r"^package\s+(\w+)", source_code, re.MULTILINE)
        if signature is None or package is None:
            raise Unexpressible("only plain Go functions are replayed")
        types, results = signature
        if len(results) not in (1, 2) or (len(results) == 2 and results[1] != "error"):
            raise Unexpressible("Go function does not return one value (and an error)")
        lines = []
        literals, skipped = _literals(calls, types, _go_literal)
        for literal in literals:
            if literal is None:
                continue
            if len(results) == 2:
                lines.append(f"\tmumeiEmit(func() (any, error) {{ return {function}({literal}) }})")
            else:
                lines.append(f"\tmumeiEmit(func() (any, error) {{ return {function}({literal}), nil }})")
        harness = (
            f"package {package.group(1)}\n\nimport (\n\t\"encoding/json\"\n\t\"fmt\"\n\t\"testing\"\n)\n\n"
            "func mumeiEmit(call func() (any, error)) {\n"
            "\trow := map[string]any{}\n"
            "\tfunc() {\n"
            "\t\tdefer func() {\n\t\t\tif r := recover(); r != nil {\n"
            "\t\t\t\trow = map[string]any{\"ok\": false, \"error\": \"panic\"}\n\t\t\t}\n\t\t}()\n"
            "\t\tv, err := call()\n"
            "\t\tif err != nil {\n\t\t\trow = map[string]any{\"ok\": false, \"error\": \"error\"}\n"
            "\t\t} else {\n\t\t\trow = map[string]any{\"ok\": true, \"value\": v}\n\t\t}\n"
            "\t}()\n"
            "\tout, err := json.Marshal(row)\n"
            "\tif err != nil {\n\t\tout = []byte(`{\"ok\": true, \"type\": \"unmarshalable\"}`)\n\t}\n"
            f"\tfmt.Println({json.dumps(MARK)} + string(out))\n}}\n\n"
            "func TestMumeiNativeReplay(t *testing.T) {\n" + "\n".join(lines) + "\n}\n"
        )
        module_root = _find_up(source_path.parent, "go.mod")
        root = module_root or source_path.parent
        if not lines:
            return _merge([], skipped)
        with tempfile.TemporaryDirectory(prefix="mumei-native-replay-") as tmp:
            work = Path(tmp) / "module"
            shutil.copytree(root, work, ignore=_IGNORE)
            if module_root is None:
                (work / "go.mod").write_text("module mumeinativereplay\n\ngo 1.18\n", encoding="utf-8")
            package_dir = work / source_path.parent.relative_to(root)
            (package_dir / "zz_mumei_native_replay_test.go").write_text(harness, encoding="utf-8")
            env = dict(os.environ)
            env["PATH"] = f"{Path(go).parent}{os.pathsep}{env.get('PATH', '')}"
            proc = subprocess.run(
                [go, "test", "-v", "-count=1", "-run", "^TestMumeiNativeReplay$", "."],
                capture_output=True, text=True, cwd=package_dir, env=env, timeout=BUILD_TIMEOUT,
            )
        rows = _parse_marked(proc.stdout)
        if len(rows) != len(lines):
            raise RuntimeError(f"the Go harness did not build or run (exit {proc.returncode})")
        return _merge([_json_number(r) for r in rows], skipped)

    def _rust(self, source_path: Path, func: str, function: str, calls: list[list[object]]) -> list[dict[str, Any]]:
        if shutil.which("cargo") is None:
            raise Unexpressible("cargo is not installed")
        types = rust_signature(func)
        root = _find_up(source_path.parent, "Cargo.toml")
        if types is None or root is None:
            raise Unexpressible("only free Rust functions in a Cargo crate are replayed")
        lines = []
        literals, skipped = _literals(calls, types, _rust_literal)
        for literal in (lit for lit in literals if lit is not None):
            lines.append(f"        mumei_emit(std::panic::catch_unwind(|| format!(\"{{:?}}\", {function}({literal}))));")
        harness = (
            "\n#[cfg(test)]\nmod mumei_native_replay {\n    #[allow(unused_imports)]\n    use super::*;\n\n"
            "    fn mumei_emit(r: std::thread::Result<String>) {\n"
            "        match r {\n"
            f"            Ok(v) => println!(\"{{}}{{{{\\\"ok\\\": true, \\\"debug\\\": {{:?}}}}}}\", {_RUST_MARK}, v),\n"
            f"            Err(_) => println!(\"{{}}{{{{\\\"ok\\\": false, \\\"error\\\": \\\"panic\\\"}}}}\", {_RUST_MARK}),\n"
            "        }\n    }\n\n"
            "    #[test]\n    fn mumei_native_replay() {\n        std::panic::set_hook(Box::new(|_| {}));\n"
            + "\n".join(lines) + "\n    }\n}\n"
        )
        if not lines:
            return _merge([], skipped)
        with tempfile.TemporaryDirectory(prefix="mumei-native-replay-") as tmp:
            work = Path(tmp) / "crate"
            shutil.copytree(root, work, ignore=_IGNORE)
            target = work / source_path.relative_to(root)
            target.write_text(target.read_text(encoding="utf-8") + harness, encoding="utf-8")
            # Release, like a shipped binary: integer overflow wraps instead of panicking.
            proc = subprocess.run(
                ["cargo", "test", "--release", "--offline", "-q", "mumei_native_replay", "--", "--nocapture",
                 "--test-threads=1"],
                capture_output=True, text=True, cwd=work, env=self._cargo_env(), timeout=BUILD_TIMEOUT,
            )
        rows = _parse_marked(proc.stdout)
        if len(rows) != len(lines):
            raise RuntimeError(f"the Rust harness did not build or run (exit {proc.returncode})")
        return _merge([_rust_row(r) for r in rows], skipped)


def _literals(
    calls: list[list[object]], types: list[str], literal: Any
) -> tuple[list[str | None], dict[int, str]]:
    """The argument list of each call, or None and the reason when a value doesn't fit its native type."""
    out: list[str | None] = []
    skipped: dict[int, str] = {}
    for i, args in enumerate(calls):
        if len(args) != len(types):
            raise Unexpressible("parameter count differs from the extracted contract")
        try:
            out.append(", ".join(literal(v, t) for v, t in zip(args, types)))
        except Unexpressible as exc:
            out.append(None)
            skipped[i] = str(exc)
    return out, skipped


def _merge(rows: list[dict[str, Any]], skipped: dict[int, str]) -> list[dict[str, Any]]:
    it = iter(rows)
    total = len(rows) + len(skipped)
    return [{"ok": False, "unexpressible": skipped[i]} if i in skipped else next(it) for i in range(total)]


def _json_number(row: dict[str, Any]) -> dict[str, Any]:
    if row.get("ok") and "value" in row and not isinstance(row["value"], (bool, int)):
        value = row.pop("value")
        if isinstance(value, float) and value.is_integer() and abs(value) < 2**53:
            row["value"] = int(value)
        else:
            row["type"] = type(value).__name__
    return row


def _rust_row(row: dict[str, Any]) -> dict[str, Any]:
    if not row.get("ok"):
        return row
    debug = str(row.get("debug", ""))
    if re.fullmatch(r"-?\d+", debug):
        return {"ok": True, "value": int(debug)}
    if debug in ("true", "false"):
        return {"ok": True, "value": debug == "true"}
    return {"ok": True, "type": "unsupported Rust value"}


class NativeReplayer:
    """Replay counterexamples and boundary inputs on the native functions of one file."""

    def __init__(self, mumei_client: Any, runner: NativeRunner | None = None) -> None:
        self.mumei_client = mumei_client
        self.runner = runner or NativeRunner()

    def replay(
        self,
        source_path: Path,
        source_code: str,
        language: str,
        forge_task_spec: dict[str, object],
        body_ports: list[dict[str, object]] = (),  # type: ignore[assignment]
        counterexample_values: list[dict[str, object]] = (),  # type: ignore[assignment]
    ) -> list[dict[str, object]]:
        atoms = _dict_list(forge_task_spec.get("atoms"))
        if not atoms and forge_task_spec.get("name"):
            atoms = [forge_task_spec]
        out: list[dict[str, object]] = []
        for atom in atoms:
            out.extend(self._replay_atom(source_path, source_code, language, atom, atoms, body_ports,
                                         counterexample_values))
        return [_redact_entry(e) for e in out]

    def _replay_atom(
        self,
        source_path: Path,
        source_code: str,
        language: str,
        atom: dict[str, object],
        atoms: list[dict[str, object]],
        body_ports: list[dict[str, object]],
        counterexample_values: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        name = _string_value(atom.get("name"), "")
        if language not in SUPPORTED_LANGUAGES:
            return [_entry(name, None, "boundary", "unsupported", f"native replay does not support {language}")]
        params = atom_params(atom)
        if params is None or _kind(_string_value(atom.get("return_type"), "i64")) not in ("int", "bool"):
            return [_entry(name, None, "boundary", "unsupported",
                           "only integer, boolean and integer-array parameters and integer or boolean results")]
        candidates: list[tuple[InputSource, object]] = []
        for port in body_ports:
            if port.get("function") == name and isinstance(port.get("counterexample"), dict):
                candidates.append(("body_port", port["counterexample"]))
        for cex in counterexample_values:
            if cex.get("function_name") == name and isinstance(cex.get("counterexample"), dict):
                candidates.append(("counterexample", cex["counterexample"]))
        entries: list[dict[str, object]] = []
        inputs: list[tuple[InputSource, dict[str, object]]] = []
        for source, raw in candidates:
            try:
                values = counterexample_input(params, raw)  # type: ignore[arg-type]
            except Unexpressible as exc:
                entries.append(_entry(name, None, source, "unexpressible", str(exc)))
                continue
            if all(values != v for _, v in inputs):
                inputs.append((source, values))
        for values in boundary_inputs(params):
            if len(inputs) >= MAX_INPUTS_PER_FUNCTION:
                break
            if all(values != v for _, v in inputs):
                inputs.append(("boundary", values))
        try:
            rows = self.runner.run(language, source_path, source_code, name,
                                   [[v[p.name] for p in params] for _, v in inputs])
        except Unexpressible as exc:
            return [*entries, _entry(name, None, "boundary", "unsupported", str(exc))]
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            reason = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
            return [*entries, _entry(name, None, "boundary", "unsupported", f"native run failed: {reason}")]
        others = [a for a in atoms if a is not atom]
        for (source, values), row in zip(inputs, rows):
            entry = self._judge(source_path, atom, params, values, row, others)
            entry["source"] = source
            entry["function"] = name
            # Boundary inputs the contract excludes say nothing; keep the report short.
            if source == "boundary" and (
                entry["verdict"] == "outside_requires"
                or (entry["verdict"] == "unexpressible" and entry["native"] is None)
            ):
                continue
            entries.append(entry)
        return entries

    def _judge(
        self,
        source_path: Path,
        atom: dict[str, object],
        params: list[Param],
        values: dict[str, object],
        row: dict[str, Any],
        others: list[dict[str, object]],
    ) -> dict[str, object]:
        entry: dict[str, object] = {"input": values, "native": dict(row)}
        if row.get("unexpressible"):
            entry["native"] = None
            entry["verdict"] = "unexpressible"
            entry["reason"] = str(row["unexpressible"])
            return entry
        if not row.get("ok"):
            # A raise is only reported for inputs the contract admits.
            verdict, reason = self._check(atom, params, values, False if _is_bool(atom) else 0, others,
                                          check_ensures=False)
            entry["verdict"] = "raised" if verdict == "meets" else verdict
            entry["reason"] = f"native code raised {row.get('error', 'an error')}" if verdict == "meets" else reason
            return entry
        if "value" not in row or isinstance(row["value"], bool) != _is_bool(atom):
            entry["verdict"] = "unexpressible"
            entry["reason"] = f"native result is {row.get('type', type(row.get('value')).__name__)}"
            return entry
        value = int(row["value"]) if row.get("bigint") else row["value"]
        verdict, reason = self._check(atom, params, values, value, others)
        entry["verdict"] = verdict
        entry["reason"] = reason
        return entry

    def _check(
        self,
        atom: dict[str, object],
        params: list[Param],
        values: dict[str, object],
        result: object,
        others: list[dict[str, object]],
        *,
        check_ensures: bool = True,
    ) -> tuple[ReplayVerdict, str]:
        try:
            module = contract_check_module(atom, params, values, result, others, check_ensures=check_ensures)
        except Unexpressible as exc:
            return "unexpressible", str(exc)
        with tempfile.TemporaryDirectory(prefix="mumei-native-replay-") as tmp:
            path = Path(tmp) / "native_replay.mm"
            path.write_text(redact_secrets(module), encoding="utf-8")
            try:
                verification = self.mumei_client.verify(str(path), report_dir=str(Path(tmp) / "report"))
            except (OSError, subprocess.SubprocessError) as exc:
                return "inconclusive", f"mumei verify failed to run: {type(exc).__name__}"
        outcome, message, _ = classify(verification)
        message = redact_secrets(message.replace(str(path), path.name).replace(tmp, ""))
        if outcome == "proven":
            return "meets", ""
        if outcome == "refuted":
            return "violates", message
        if _REQUIRES_CONTRADICTION.search(message):
            return "outside_requires", ""
        return "inconclusive", message


def _is_bool(atom: dict[str, object]) -> bool:
    return _kind(_string_value(atom.get("return_type"), "i64")) == "bool"


def _redact_scalars(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _redact_scalars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_scalars(v) for v in value]
    if isinstance(value, int) and not isinstance(value, bool) and redact_secrets(str(value)) != str(value):
        return REDACTED
    return value


def _redact_entry(entry: dict[str, object]) -> dict[str, object]:
    """The entry with sensitive values removed, numbers included."""
    return redact_value(_redact_scalars(entry))


def _entry(function: str, values: object, source: str, verdict: str, reason: str) -> dict[str, object]:
    return {"function": function, "input": values, "source": source, "native": None, "verdict": verdict,
            "reason": reason}


def native_replay_violations(replays: list[dict[str, object]]) -> list[str]:
    """One confirmed code finding per input whose native result breaks the contract."""
    out = []
    for r in replays:
        if r.get("verdict") != "violates":
            continue
        native = r.get("native") or {}
        out.append(redact_secrets(
            f"native-replay: {r['function']}: the native function breaks the extracted contract on "
            f"{json.dumps(r['input'], sort_keys=True)} (returned {json.dumps(native.get('value'))}; "
            f"input from {r['source']})"
        ))
    return out


def reconcile_body_ports(body_ports: list[dict[str, object]], replays: list[dict[str, object]]) -> set[str]:
    """Mark each port with what the native code did; return the functions whose refutation did not reproduce."""
    not_reproduced: set[str] = set()
    for port in body_ports:
        name = port.get("function")
        mine = [r for r in replays if r.get("function") == name]
        if port.get("outcome") == "refuted":
            witness = [r for r in mine if r.get("source") == "body_port"]
            if any(r.get("verdict") == "violates" for r in witness):
                port["native_replay"] = "reproduced"
            elif witness and all(r.get("verdict") == "meets" for r in witness):
                port["native_replay"] = "not_reproduced"
                not_reproduced.add(str(name))
            else:
                port["native_replay"] = "not_checked"
        elif port.get("outcome") == "proven" and any(r.get("verdict") == "violates" for r in mine):
            # The port was proven but the native code breaks the contract: the port changed the behaviour.
            port["native_replay"] = "port_mismatch"
    return not_reproduced
