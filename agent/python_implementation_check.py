"""Check extracted postconditions against a small Python normal-return fragment."""
from __future__ import annotations

import ast
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from agent.cross_validation_models import ForeignCodeVerdict, MumeiContractAtom
from agent.secret_redaction import redact_secrets, redact_value

if TYPE_CHECKING:
    from agent.audit_models import MumeiVerifyClientLike

_MAX_SOURCE_CHARS = 64_000
_MAX_CLAUSE_CHARS = 2_000
_MAX_FUNCTION_NODES = 256
_SCALAR_TYPES = {"int": "i64", "bool": "bool"}
_ARITHMETIC = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*"}
_COMPARISONS = {ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">="}
_EQUALITIES = {ast.Eq: "==", ast.NotEq: "!="}
_TRIVIAL = {"", "true", "1"}


@dataclass(frozen=True)
class ImplementationCheck:
    function: str
    status: ForeignCodeVerdict
    counterexample: dict[str, str | int | bool] = field(default_factory=dict)

    @property
    def violation(self) -> str:
        return f"{self.function}: Python return violates the extracted postcondition (Z3 counterexample)."


class _Unsupported(ValueError):
    pass


def _expr(node: ast.AST | None, names: dict[str, str]) -> tuple[str, str]:
    if isinstance(node, ast.Name) and node.id in names:
        return node.id, names[node.id]
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return str(node.value).lower(), "bool"
        if isinstance(node.value, int) and node.value.bit_length() <= 63:
            return str(node.value), "i64"
    if isinstance(node, ast.UnaryOp):
        operand, kind = _expr(node.operand, names)
        if isinstance(node.op, ast.USub) and kind == "i64":
            return f"(-{operand})", kind
        if isinstance(node.op, ast.Not) and kind == "bool":
            return f"(!{operand})", kind
    if isinstance(node, ast.BinOp):
        op = _ARITHMETIC.get(type(node.op))
        lhs, left_kind = _expr(node.left, names)
        rhs, right_kind = _expr(node.right, names)
        if op and left_kind == right_kind == "i64":
            return f"({lhs} {op} {rhs})", "i64"
    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        op = type(node.ops[0])
        lhs, left_kind = _expr(node.left, names)
        rhs, right_kind = _expr(node.comparators[0], names)
        if op in _EQUALITIES and left_kind == right_kind:
            return f"({lhs} {_EQUALITIES[op]} {rhs})", "bool"
        if op in _COMPARISONS and left_kind == right_kind == "i64":
            return f"({lhs} {_COMPARISONS[op]} {rhs})", "bool"
    if isinstance(node, ast.BoolOp):
        parts = [_expr(value, names) for value in node.values]
        if all(kind == "bool" for _, kind in parts):
            op = " && " if isinstance(node.op, ast.And) else " || "
            return f"({op.join(expr for expr, _ in parts)})", "bool"
    raise _Unsupported


def _annotation_type(node: ast.AST | None) -> str:
    if isinstance(node, ast.Name) and node.id in _SCALAR_TYPES:
        return _SCALAR_TYPES[node.id]
    raise _Unsupported


def _probe_module(node: ast.FunctionDef, atom: MumeiContractAtom) -> str:
    args = node.args
    if (
        node.decorator_list or args.vararg or args.kwarg or args.kwonlyargs
        or atom.effects or len(atom.ensures) > _MAX_CLAUSE_CHARS or "#" in atom.ensures
        or sum(1 for _ in ast.walk(node)) > _MAX_FUNCTION_NODES
    ):
        raise _Unsupported
    params = {arg.arg: _annotation_type(arg.annotation) for arg in [*args.posonlyargs, *args.args]}
    returns = _annotation_type(node.returns)
    if (
        list(params.items()) != [(param.name, param.type) for param in atom.params]
        or returns != atom.return_type
        or "result" in params or any(not name.isascii() for name in params)
    ):
        raise _Unsupported

    statements = node.body
    if ast.get_docstring(node) is not None:
        statements = statements[1:]
    if not statements or not isinstance(statements[-1], ast.Return):
        raise _Unsupported
    guards: list[str] = []
    for guard in statements[:-1]:
        if (
            not isinstance(guard, ast.If) or guard.orelse
            or len(guard.body) != 1 or not isinstance(guard.body[0], ast.Raise)
        ):
            raise _Unsupported
        predicate, kind = _expr(guard.test, params)
        if kind != "bool":
            raise _Unsupported
        guards.append(predicate)
    body, body_type = _expr(statements[-1].value, params)
    clause = atom.ensures.replace("&&", " and ").replace("||", " or ")
    clause = re.sub(r"!(?!=)", " not ", clause)
    clause = re.sub(r"\b(true|false)\b", lambda match: match[0].capitalize(), clause)
    ensures, ensures_type = _expr(ast.parse(clause.strip(), mode="eval").body, {**params, "result": returns})
    if body_type != returns or ensures_type != "bool":
        raise _Unsupported
    # A rejecting path owes no postcondition. Put this implication in ensures
    # so a postcondition impossible on every returning path still yields a model.
    if guards:
        ensures = f"({' || '.join(guards)} || {ensures})"
    signature = ", ".join(f"{name}: {kind}" for name, kind in params.items())
    return (
        f"atom python_implementation({signature}) -> {returns} {{\n"
        "    requires: true;\n"
        f"    ensures: {ensures};\n"
        f"    body: {{ {body} }}\n"
        "}\n"
    )


def _check_one(
    node: ast.FunctionDef, atom: MumeiContractAtom, verifier: MumeiVerifyClientLike,
) -> ImplementationCheck:
    name = redact_secrets(atom.name)
    inconclusive = ImplementationCheck(name, "unverifiable")
    try:
        module = _probe_module(node, atom)
        if redact_secrets(module) != module:
            return inconclusive
        with tempfile.TemporaryDirectory(prefix="mumei-python-implementation-") as tmp:
            path = Path(tmp) / "python_implementation.mm"
            path.write_text(module, encoding="utf-8")
            verification = verifier.verify(
                str(path), report_dir=str(Path(tmp) / "report"),
                extra_args=["--solver-timeout", "1000"],
            )
    except (SyntaxError, _Unsupported, RecursionError, OSError, subprocess.SubprocessError):
        return inconclusive
    report = verification.get("report")
    if not isinstance(report, dict):
        return inconclusive
    status = report.get("status")
    if verification.get("success") is True and status in ("success", "verified"):
        return ImplementationCheck(name, "verified")
    model = report.get("counterexample")
    if (
        verification.get("success") is False and status == "failed"
        and report.get("failure_type") == "postcondition_violated"
        and report.get("counterexample_fidelity", "exact") == "exact"
        and isinstance(model, dict) and model
    ):
        params = {param.name for param in atom.params}
        if model.keys() <= params and all(isinstance(value, (str, int)) for value in model.values()):
            # Redact integer values too, if their textual form matches a credential.
            safe_model = redact_value({key: str(value) for key, value in model.items()})
            return ImplementationCheck(name, "refuted", safe_model)
    return inconclusive


def check_python_implementations(
    source: str, atoms: list[MumeiContractAtom], verifier: MumeiVerifyClientLike,
) -> list[ImplementationCheck]:
    candidates = [atom for atom in atoms if atom.ensures.strip().lower() not in _TRIVIAL]
    if not candidates:
        return []
    if len(source) > _MAX_SOURCE_CHARS:
        return [ImplementationCheck(redact_secrets(atom.name), "unverifiable") for atom in candidates]
    try:
        tree = ast.parse(source)
    except (SyntaxError, RecursionError, ValueError):
        return [ImplementationCheck(redact_secrets(atom.name), "unverifiable") for atom in candidates]
    top_level = {id(node) for node in tree.body}
    functions: dict[str, list[ast.FunctionDef | ast.AsyncFunctionDef]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.setdefault(node.name, []).append(node)
    checks = []
    for atom in candidates:
        matches = functions.get(atom.name, [])
        if not matches:
            continue
        node = matches[0]
        if len(matches) != 1 or not isinstance(node, ast.FunctionDef) or id(node) not in top_level:
            checks.append(ImplementationCheck(redact_secrets(atom.name), "unverifiable"))
        else:
            checks.append(_check_one(node, atom, verifier))
    return checks
