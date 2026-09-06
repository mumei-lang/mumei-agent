"""Task 2-D — AI-generated Lean proofs for residual ``unknown`` atoms.

This module sits *after* the Task 2-C bridge (generated-module path and
known witness modules) and *before* human review.  For every atom that is
still ``z3_check_result == "unknown"`` it asks an LLM to write a Lean 4
module containing ``theorem <atom>_correct``, builds that module with
``lake build`` inside the configured ``mumei-lean`` checkout, and feeds the
build log back to the LLM for repair up to a bounded number of attempts.

Soundness contract
------------------

* The theorem *statement* is never written by the LLM.  Each run re-runs
  the trusted translator (``scripts/ingest_cert.py``) on the certificate
  being repaired into ``<evidence>/_statements/`` and takes the statement
  verbatim from there -- never from ``<mumei-lean>/generated/``, where a
  failed bridge may have left a stale module.  The LLM supplies only the
  tactic script after ``:= by``; atoms for which the translator emits no
  statement are skipped (``no_trusted_statement``) and stay ``unknown``.
* An atom is promoted to ``lean_verified`` **only** when Lake compiles the
  assembled module with exit code 0, no ``error:`` lines, no
  ``declaration uses 'sorry'`` warning, and ``#print axioms`` reports
  nothing beyond ``propext`` / ``Classical.choice`` / ``Quot.sound``.
* Tactic scripts that contain ``sorry`` / ``admit`` / ``native_decide`` /
  ``axiom`` / ``unsafe`` / meta-programming or IO escapes (``run_cmd``,
  ``run_tac``, ``#eval``, ``set_option`` ...) are rejected before Lake.
* Every attempt's Lean source and build log is copied to an evidence
  directory, and promoted atoms carry ``ai_proof_used = True`` in both
  ``lean_metadata`` and ``lean_result_metadata`` so provenance is
  distinguishable from ``known_witness_used`` and the generated-module path.
* The generated module is removed from the ``mumei-lean`` checkout after
  each attempt so a stale AI module can never influence later
  ``scripts/bridge.py`` runs.

The module never imports ``mumei-lean``; Lake is invoked as a subprocess.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import subprocess
import sys
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from agent.lean_bridge_helpers import (
    _classify_bridge_failure,
    _coerce_output,
    _load_json_file,
    _mumei_lean_bridge_contract,
    _result,
    _upgrade_atoms_by_name,
    extract_unknown_atoms,
)
from agent.proofcert import VerificationStatus, Z3CheckResult

logger = logging.getLogger(__name__)

AI_PROOF_STRATEGY = "ai_generated_proof"
AI_PROOF_MODULE_ROOT = "Generated.AiProof"
DEFAULT_AI_PROOF_MAX_ATTEMPTS = 3

_SORRY_RE = re.compile(r"declaration uses 'sorry'")
_ERROR_LINE_RE = re.compile(r"(^|\n)[^\n]*\berror:")
_AXIOMS_RE = re.compile(
    r"'(?P<decl>[^']+)' depends on axioms: \[(?P<axioms>[^\]]*)\]"
)
_NO_AXIOMS_RE = re.compile(r"'(?P<decl>[^']+)' does not depend on any axioms")
ALLOWED_AXIOMS = frozenset({"propext", "Classical.choice", "Quot.sound"})
_FORBIDDEN_TOKENS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("sorry", re.compile(r"\bsorry\b")),
    ("admit", re.compile(r"\badmit\b")),
    ("axiom", re.compile(r"\baxiom\b")),
    ("unsafe", re.compile(r"\bunsafe\b")),
    ("implemented_by", re.compile(r"implemented_by")),
    ("extern", re.compile(r"@\[\s*extern")),
    ("native_decide", re.compile(r"\bnative_decide\b")),
    ("run_cmd", re.compile(r"\brun_cmd\b")),
    ("run_tac", re.compile(r"\brun_tac\b")),
    ("eval", re.compile(r"#eval\b|#exit\b|#print\b")),
    ("set_option", re.compile(r"\bset_option\b")),
    ("initialize", re.compile(r"\binitialize\b")),
    ("elab", re.compile(r"\b(?:macro|macro_rules|elab|elab_rules|syntax|notation)\b")),
    ("io", re.compile(r"\bIO\.")),
    ("declaration", re.compile(r"(^|\n)\s*(?:theorem|lemma|def|abbrev|instance|axiom|opaque|namespace|end|section|import|open|variable|attribute|local|scoped|private|protected|noncomputable|partial|structure|inductive|class|example)\b")),
)
_DECL_START_RE = re.compile(
    r"^(?:@\[[^\]]*\]\s*)?(?:private\s+|protected\s+|noncomputable\s+)*"
    r"(?P<kind>theorem|lemma|example)\b(?:\s+(?P<name>[^\s(:{\[]+))?"
)
_PROOF_START_RE = re.compile(r":=\s*by\b")


@dataclass
class TrustedStatement:
    """Theorem statement lifted from a bridge-generated Lean module."""

    source_path: str
    namespace: str
    theorem_name: str
    header: str
    preamble: str


def _split_top_level_blocks(source: str) -> list[str]:
    blocks: list[list[str]] = []
    for line in source.splitlines():
        if line and not line[0].isspace() and not (
            blocks and blocks[-1] and _in_block_comment("\n".join(blocks[-1]))
        ):
            blocks.append([line])
        elif blocks:
            blocks[-1].append(line)
        else:
            blocks.append([line])
    return ["\n".join(block) for block in blocks]


def _in_block_comment(text: str) -> bool:
    return text.count("/-") > text.count("-/")


def bridge_module_key_for(cert: dict[str, Any], atom: dict[str, Any]) -> str | None:
    """Module key ``scripts/ingest_cert.py`` derives for this certificate.

    Mirrors ``_module_key_from_certificate``: ``cert["file"]`` minus ``.mm``
    / leading ``./`` (default ``atom_module``).  ``atom["module_key"]`` is
    only a fallback when the certificate carries no ``file``.
    """
    file = cert.get("file")
    if isinstance(file, str) and file:
        return file.removesuffix(".mm").removeprefix("./") or "atom_module"
    key = atom.get("module_key")
    if isinstance(key, str) and key:
        return key
    return "atom_module"


def bridge_module_path_for(
    repo_path: Path, module_key: str, *, generated_root: Path | None = None
) -> Path:
    """Mirror of ``ingest_cert._module_to_path``: ``std/core`` → ``Generated/Std/Core.lean``."""
    parts = [p for p in module_key.replace("\\", "/").split("/") if p]
    segments = [AI_PROOF_MODULE_ROOT.split(".")[0]]
    for part in parts:
        clean = "".join(c if c.isalnum() or c == "_" else "_" for c in part)
        if not clean:
            clean = "M"
        if clean[0].isdigit():
            clean = "M" + clean
        segments.append(clean[:1].upper() + clean[1:])
    base = generated_root if generated_root is not None else repo_path / "generated"
    return (base / Path(*segments)).with_suffix(".lean")


def _run_translator(
    cmd: list[str], *, cwd: str, timeout: float | None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False
    )


def regenerate_trusted_modules(
    repo_path: Path,
    cert: dict[str, Any],
    out_dir: Path,
    *,
    timeout: float | None = 120.0,
) -> Path | None:
    """Run ``scripts/ingest_cert.py`` on *cert* into a fresh *out_dir*.

    The statements the AI stage proves are lifted from this output rather
    than from ``<repo>/generated``, so they always describe the certificate
    being repaired and never a stale module left behind by an earlier or
    failed bridge run.  Returns the output directory, or ``None`` (fail
    closed) when the translator is missing or errors out.
    """
    script = repo_path / "scripts" / "ingest_cert.py"
    if not script.is_file():
        return None
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        cert_path = out_dir / "input.proof-cert.json"
        cert_path.write_text(json.dumps(cert), encoding="utf-8")
        proc = _run_translator(
            [sys.executable, str(script), str(cert_path), "--out", str(out_dir)],
            cwd=str(repo_path),
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("ingest_cert regeneration failed: %s", exc)
        return None
    if proc.returncode != 0:
        logger.warning("ingest_cert exited %d: %s", proc.returncode, proc.stderr[-500:])
        return None
    return out_dir


def find_trusted_statement(
    repo_path: Path,
    atom_name: str,
    *,
    theorem_name: str,
    module_key: str | None = None,
    generated_root: Path | None = None,
) -> TrustedStatement | None:
    """Locate ``theorem <theorem_name>`` in the bridge-generated module tree.

    With *module_key* only the module ``scripts/bridge.py`` emits for that
    key is consulted, so a same-named theorem in another (possibly stale)
    generated module can never be picked up.  Without a key the whole
    ``<repo>/generated/Generated/**/*.lean`` tree (minus the AI module
    directory) is searched and the statement is accepted only when it is
    unique.  Returns the statement header, the module's non-theorem
    declarations (imports / ``open`` / helper ``def``s) and its namespace;
    ``None`` when the translator never produced an unambiguous statement
    for the atom (``partial_translation`` etc.).  *generated_root*
    replaces ``<repo>/generated`` (see :func:`regenerate_trusted_modules`).
    """
    base = generated_root if generated_root is not None else repo_path / "generated"
    root = base / AI_PROOF_MODULE_ROOT.split(".")[0]
    if not root.is_dir():
        return None
    ai_root = ai_proof_module_path(repo_path, AI_PROOF_MODULE_ROOT).with_suffix("")
    if module_key is not None:
        candidates = [
            bridge_module_path_for(repo_path, module_key, generated_root=base)
        ]
    else:
        candidates = [
            c
            for c in sorted(root.rglob("*.lean"))
            if ai_root not in c.parents and c != ai_root
        ]
    found: list[TrustedStatement] = []
    for candidate in candidates:
        try:
            text = candidate.read_text(encoding="utf-8")
        except OSError:
            continue
        if not re.search(rf"\btheorem\s+{re.escape(theorem_name)}\b", text):
            continue
        statement = _lift_statement(text, theorem_name, str(candidate))
        if statement is not None:
            found.append(statement)
    if len(found) != 1:
        return None
    return found[0]


def _lift_statement(
    text: str, theorem_name: str, source_path: str
) -> TrustedStatement | None:
    namespace = ""
    ns_match = re.search(r"^namespace\s+(\S+)", text, re.MULTILINE)
    if ns_match:
        namespace = ns_match.group(1)
    header: str | None = None
    preamble: list[str] = []
    for block in _split_top_level_blocks(text):
        first = block.lstrip("\n").split("\n", 1)[0]
        decl = _DECL_START_RE.match(first)
        if decl is None:
            stripped = block.strip()
            if stripped.startswith("end ") or stripped == "end":
                continue
            if stripped.startswith("/--") and stripped.endswith("-/"):
                continue
            preamble.append(block)
            continue
        if decl.group("name") != theorem_name:
            continue
        proof = _PROOF_START_RE.search(block)
        cut = proof.start() if proof else block.rfind(":=")
        if cut < 0:
            return None
        header = block[:cut].rstrip()
    if header is None:
        return None
    return TrustedStatement(
        source_path=source_path,
        namespace=namespace,
        theorem_name=theorem_name,
        header=header,
        preamble="\n".join(preamble).strip("\n"),
    )


def assemble_ai_module(
    statement: TrustedStatement, *, module: str, tactics: str, nonce: str
) -> str:
    """Trusted preamble + trusted header + AI tactic script + axiom audit."""
    preamble = statement.preamble
    if statement.namespace:
        preamble = re.sub(
            rf"^namespace\s+{re.escape(statement.namespace)}\s*$",
            f"namespace {module}",
            preamble,
            flags=re.MULTILINE,
        )
    if not re.search(r"^namespace\s", preamble, re.MULTILINE):
        preamble = f"{preamble}\n\nnamespace {module}"
    body = "\n".join(
        f"  {line}" if line.strip() else "" for line in tactics.strip("\n").splitlines()
    )
    return (
        f"{preamble}\n\n-- ai-proof attempt {nonce}\n"
        f"{statement.header} := by\n{body}\n\n"
        f"#print axioms {statement.theorem_name}\n\nend {module}\n"
    )


class AiProofGenerator(Protocol):
    """Anything that can turn a proof request into Lean 4 source."""

    def generate_lean_proof(self, request: dict[str, Any]) -> str:
        ...


@dataclass
class AiProofAttempt:
    attempt: int
    accepted: bool
    error_code: str | None
    source_path: str | None
    log_path: str | None
    rejection_reason: str | None = None


@dataclass
class AiProofAtomOutcome:
    name: str
    proved: bool
    attempts: list[AiProofAttempt] = field(default_factory=list)
    module: str | None = None
    theorem: str | None = None
    error_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "proved": self.proved,
            "attempts": len(self.attempts),
            "module": self.module,
            "theorem": self.theorem,
            "error_code": self.error_code,
            "attempt_log": [
                {
                    "attempt": a.attempt,
                    "accepted": a.accepted,
                    "error_code": a.error_code,
                    "source_path": a.source_path,
                    "log_path": a.log_path,
                    "rejection_reason": a.rejection_reason,
                }
                for a in self.attempts
            ],
        }


def sanitize_lean_module_name(atom_name: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_]", "_", atom_name)
    if not cleaned or not (cleaned[0].isalpha() or cleaned[0] == "_"):
        cleaned = f"A_{cleaned}"
    return cleaned[0].upper() + cleaned[1:]


def ai_proof_module_for(atom_name: str) -> str:
    return f"{AI_PROOF_MODULE_ROOT}.{sanitize_lean_module_name(atom_name)}"


def ai_proof_module_path(repo_path: Path, module: str) -> Path:
    return repo_path / "generated" / Path(*module.split(".")).with_suffix(".lean")


def extract_lean_source(text: str) -> str:
    """Strip Markdown fences from an LLM reply, keeping the Lean body."""
    stripped = text.strip()
    if "```" not in stripped:
        return stripped
    blocks = re.findall(r"```(?:lean4?|Lean4?)?\s*\n(.*?)```", stripped, re.DOTALL)
    if blocks:
        return max(blocks, key=len).strip()
    return stripped.replace("```", "").strip()


def extract_tactic_script(text: str, theorem_name: str) -> str:
    """Reduce an LLM reply to the tactic script that follows ``:= by``.

    Accepts either a bare tactic block or a full theorem (in which case
    everything up to and including the theorem's ``:= by`` is dropped).
    """
    source = extract_lean_source(text)
    decl = re.search(rf"\btheorem\s+{re.escape(theorem_name)}\b", source)
    if decl is not None:
        proof = _PROOF_START_RE.search(source, decl.end())
        if proof is not None:
            source = source[proof.end():]
        else:
            return ""
    stripped = source.strip("\n")
    if stripped.lstrip().startswith("by") and re.match(r"\s*by\b", stripped):
        stripped = re.sub(r"^\s*by\b", "", stripped, count=1)
    lines = stripped.strip("\n").splitlines()
    if not lines:
        return ""
    # ``extract_lean_source`` already stripped the first line's indent, so
    # measure the common indent on the remaining lines only.
    rest = lines[1:]
    indents = [len(l) - len(l.lstrip()) for l in rest if l.strip()]
    common = min(indents) if indents else 0
    out = [lines[0].strip()]
    out.extend(l[common:].rstrip() if l.strip() else "" for l in rest)
    return "\n".join(out).strip("\n")


def reject_unsound_lean_source(source: str, theorem_name: str) -> str | None:
    """Return a rejection reason when the tactic script must not reach Lake.

    *source* is the AI-supplied tactic script only; the theorem statement
    is trusted and assembled separately (:func:`assemble_ai_module`).
    """
    if not source.strip():
        return "empty_source"
    for label, pattern in _FORBIDDEN_TOKENS:
        if pattern.search(source):
            return f"forbidden_token:{label}"
    return None


def _audit_axioms(
    log: str, theorem_name: str, *, module: str | None = None
) -> str | None:
    """Return an error code unless ``#print axioms`` reports only ALLOWED_AXIOMS.

    Lean prints the fully-qualified declaration name; with *module* the
    match is exact (``<module>.<theorem_name>``), otherwise the qualified
    name must end in ``.<theorem_name>`` (or be the bare name).
    """

    def is_target(decl: str) -> bool:
        if module is not None:
            return decl == f"{module}.{theorem_name}"
        return decl == theorem_name or decl.endswith(f".{theorem_name}")

    for match in _NO_AXIOMS_RE.finditer(log):
        if is_target(match.group("decl")):
            return None
    for match in _AXIOMS_RE.finditer(log):
        if not is_target(match.group("decl")):
            continue
        axioms = {a.strip() for a in match.group("axioms").split(",") if a.strip()}
        if axioms - ALLOWED_AXIOMS:
            return "unsound_axioms"
        return None
    return "axiom_audit_missing"


def build_ai_proof_request(
    atom: dict[str, Any],
    *,
    module: str,
    theorem_name: str,
    escalation_bundle: dict[str, Any] | None,
    feedback: list[dict[str, Any]],
    statement: TrustedStatement | None = None,
) -> dict[str, Any]:
    """Assemble the structured request handed to the generator."""
    bundle_hints: dict[str, Any] = {}
    if isinstance(escalation_bundle, dict):
        for key in ("counterexamples", "tried_invariants", "loop_context", "reason"):
            if escalation_bundle.get(key):
                bundle_hints[key] = escalation_bundle[key]
        bundle_atom = escalation_bundle.get("atom")
        if isinstance(bundle_atom, dict) and bundle_atom.get("name") == atom.get(
            "name"
        ):
            bundle_hints["atom"] = bundle_atom
    return {
        "module": module,
        "theorem_name": theorem_name,
        "atom": {
            key: atom[key]
            for key in (
                "name",
                "module_key",
                "params",
                "return_type",
                "requires",
                "ensures",
                "body",
                "body_expr",
                "escalation_reason",
                "logic_fragment_tags",
                "unknown_obligation_domain",
            )
            if atom.get(key) is not None
        },
        "escalation_bundle": bundle_hints,
        "feedback": [dict(item) for item in feedback],
        "statement": (
            {
                "header": statement.header,
                "preamble": statement.preamble,
                "source_path": statement.source_path,
            }
            if statement is not None
            else None
        ),
    }


def render_ai_proof_prompt(request: dict[str, Any]) -> str:
    atom = request["atom"]
    statement = request.get("statement") or {}
    header = statement.get("header") or f"theorem {request['theorem_name']}"
    lines = [
        (
            "Write a Lean 4 tactic script (Mathlib and MumeiLean available) that "
            "closes the goal of the theorem below.  The statement is fixed and "
            "will be compiled verbatim; return ONLY the tactic lines that follow "
            "`:= by`."
        ),
        "",
        (
            "Do NOT use `sorry`, `admit`, `axiom`, `unsafe`, `native_decide`, "
            "`run_cmd`, `run_tac`, `#eval`, `set_option`, or new declarations; "
            "the proof must fully elaborate under `lake build`."
        ),
        "",
        "Module context (imports / helper definitions, trusted, do not repeat):",
        "```lean",
        str(statement.get("preamble") or "import MumeiLean"),
        "```",
        "",
        "Theorem to prove (statement is fixed):",
        "```lean",
        f"{header} := by",
        "  -- your tactic script here",
        "```",
        "",
        "Mumei atom contract (for intuition only):",
        json.dumps(atom, indent=2, ensure_ascii=False),
    ]
    hints = request.get("escalation_bundle") or {}
    if hints:
        lines += [
            "",
            "Z3 escalation hints (counterexamples / tried invariants):",
            json.dumps(hints, indent=2, ensure_ascii=False),
        ]
    feedback = request.get("feedback") or []
    if feedback:
        lines += ["", "Previous attempts failed. Fix the proof using this feedback:"]
        for item in feedback:
            lines.append(
                f"- attempt {item.get('attempt')}: "
                f"{item.get('error_code') or item.get('rejection_reason')}"
            )
            log_tail = item.get("log_tail")
            if log_tail:
                lines.append("```")
                lines.append(str(log_tail))
                lines.append("```")
    lines += ["", "Return ONLY the tactic script, in a single ```lean code block."]
    return "\n".join(lines)


class LLMAiProofGenerator:
    """OpenAI-compatible generator built from :class:`agent.config.AgentConfig`."""

    def __init__(self, config: Any, client: Any | None = None) -> None:
        self.config = config
        self._client = client

    def generate_lean_proof(self, request: dict[str, Any]) -> str:
        if self._client is None:
            self._client = self.config.create_client()
        kwargs: dict[str, Any] = {}
        max_tokens = getattr(self.config, "llm_max_tokens", None)
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        response = self._client.chat.completions.create(
            model=self.config.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert Lean 4 / Mathlib prover. You output "
                        "only tactic scripts that fully elaborate for the given "
                        "fixed theorem statement."
                    ),
                },
                {"role": "user", "content": render_ai_proof_prompt(request)},
            ],
            **kwargs,
        )
        return response.choices[0].message.content or ""


def _lake_build_module(
    repo_path: Path,
    module: str,
    *,
    timeout: float | None,
) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["lake", "build", module],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        log = (
            f"{_coerce_output(exc.stdout)}\n{_coerce_output(exc.stderr)}\n"
            f"error: lake build timed out after {timeout} seconds"
        )
        return -1, log
    except OSError as exc:
        return -1, f"error: could not execute lake: {exc}"
    return proc.returncode, f"{proc.stdout}\n{proc.stderr}"


def _build_log_accepts(
    returncode: int,
    log: str,
    *,
    theorem_name: str | None = None,
    module: str | None = None,
) -> tuple[bool, str | None]:
    if returncode != 0:
        if "lake build timed out" in log:
            return False, "timeout"
        error_code, _ = _classify_bridge_failure(
            stdout=log, stderr="", returncode=returncode
        )
        return False, error_code or "bridge_failed"
    if _SORRY_RE.search(log):
        return False, "tactic_failed"
    if _ERROR_LINE_RE.search(log):
        return False, "bridge_failed"
    if theorem_name is not None:
        audit = _audit_axioms(log, theorem_name, module=module)
        if audit is not None:
            return False, audit
    return True, None


def _tail(text: str, limit: int = 2000) -> str:
    return text[-limit:] if len(text) > limit else text


def _redact_log(log: str, repo_path: Path) -> str:
    """Strip checkout-local paths before a build log is shown to the model."""
    redacted = log.replace(str(repo_path.resolve()), "<mumei-lean>")
    redacted = redacted.replace(str(repo_path), "<mumei-lean>")
    return redacted.replace(str(Path.home()), "~")


def annotate_residual_atoms(
    cert: dict[str, Any], outcomes: list[dict[str, Any]]
) -> None:
    """Attach failed AI outcomes (``ai_proof_outcome``) to still-unknown atoms.

    Mutates *cert* in place; only atoms whose ``z3_check_result`` is still
    ``unknown`` and whose name is unique in the certificate are annotated,
    so the human final fallback (``human_review.escalate_to_lean``) can
    report what the automated stage already tried.
    """
    by_name = {
        o["name"]: o for o in outcomes if not o.get("proved") and isinstance(o.get("name"), str)
    }
    if not by_name:
        return
    atoms = cert.get("atoms")
    if not isinstance(atoms, list):
        return
    counts = Counter(a.get("name") for a in atoms if isinstance(a, dict))
    for atom in atoms:
        if not isinstance(atom, dict):
            continue
        name = atom.get("name")
        outcome = by_name.get(name)
        if (
            outcome is None
            or counts[name] != 1
            or atom.get("z3_check_result") != Z3CheckResult.UNKNOWN.value
        ):
            continue
        atom["ai_proof_outcome"] = json.loads(json.dumps(outcome))


def _ai_proof_atom_record(
    atom: dict[str, Any],
    *,
    module: str,
    theorem_name: str,
    attempts: int,
    source_path: str,
    log_path: str,
    bridge_contract: dict[str, str],
    statement_path: str | None = None,
) -> dict[str, Any]:
    record = json.loads(json.dumps(atom))
    record["z3_check_result"] = Z3CheckResult.LEAN_VERIFIED.value
    record["status"] = VerificationStatus.VERIFIED.value
    existing_metadata = atom.get("lean_metadata")
    metadata = dict(existing_metadata) if isinstance(existing_metadata, dict) else {}
    diagnostics = metadata.get("diagnostics")
    diagnostics = list(diagnostics) if isinstance(diagnostics, list) else []
    if AI_PROOF_STRATEGY not in diagnostics:
        diagnostics.append(AI_PROOF_STRATEGY)
    metadata.update(
        {
            "status": "lean_verified",
            "theorem_name": theorem_name,
            "lean_module": module,
            "lean_theorem_name": f"{module}.{theorem_name}",
            "known_witness_used": False,
            "ai_proof_used": True,
            "ai_proof_attempts": attempts,
            "proof_path": source_path,
            "build_log_path": log_path,
            "statement_source_path": statement_path,
            "diagnostics": diagnostics,
            "proof_strategy": {
                "strategy": AI_PROOF_STRATEGY,
                "module": module,
                "theorem": theorem_name,
            },
        }
    )
    for field_name in (
        "z3_result_class",
        "escalation_reason",
        "logic_fragment_tag",
        "logic_fragment_tags",
        "unknown_obligation_domain",
    ):
        value = atom.get(field_name)
        if value:
            metadata.setdefault(field_name, value)
    for const_key, field_name in (
        ("TRANSLATOR_VERSION", "translator_version"),
        ("BRIDGE_LEMMA_HASH", "bridge_lemma_hash"),
    ):
        value = bridge_contract.get(const_key)
        if value:
            record[field_name] = value
            metadata[field_name] = value
        elif isinstance(atom.get(field_name), str):
            record[field_name] = atom[field_name]
            metadata.setdefault(field_name, atom[field_name])
    record["lean_metadata"] = metadata
    record["lean_result_metadata"] = {
        "fallback_strategy": AI_PROOF_STRATEGY,
        "known_witness_used": False,
        "ai_proof_used": True,
        "ai_proof_attempts": attempts,
    }
    return record


def run_ai_proof_repair(
    *,
    cert: dict[str, Any],
    mumei_lean_repo: str | Path,
    generator: AiProofGenerator,
    escalation_bundle: dict[str, Any] | None = None,
    max_attempts: int = DEFAULT_AI_PROOF_MAX_ATTEMPTS,
    timeout: float | None = 600.0,
    evidence_dir: str | Path | None = None,
    skip_names: set[str] | None = None,
) -> dict[str, Any] | None:
    """Generate → Lake build → repair for every residual unknown atom in *cert*.

    Returns ``None`` when there is nothing to attempt, otherwise a result
    dict shaped like :func:`agent.lean_bridge_helpers._result` whose
    ``lean_cert`` upgrades exactly the atoms Lake accepted.
    """
    unknown_atoms = [
        atom
        for atom in extract_unknown_atoms(cert)
        if isinstance(atom.get("name"), str)
        and atom["name"] not in (skip_names or set())
    ]
    if not unknown_atoms:
        return None
    if max_attempts < 1:
        logger.warning("ai proof repair disabled: max_attempts=%d", max_attempts)
        return None
    name_counts = Counter(atom["name"] for atom in unknown_atoms)
    ambiguous = {name for name, n in name_counts.items() if n > 1}
    repo_path = Path(mumei_lean_repo)
    if shutil.which("lake") is None:
        return _result(
            success=False,
            returncode=-1,
            stderr="lake not found on PATH",
            error_code="lake_missing",
            diagnostics=["AI proof generation requires Lake to check generated modules."],
            extra={"fallback_strategy": AI_PROOF_STRATEGY, "ai_proof_used": False},
        )
    run_tag = uuid.uuid4().hex[:8]
    run_id = f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{run_tag}"
    evidence_root = (
        Path(evidence_dir)
        if evidence_dir is not None
        else repo_path / ".ai_proof_evidence"
    ) / run_id
    bridge_contract = _mumei_lean_bridge_contract(repo_path)
    started = time.monotonic()
    statements_root = regenerate_trusted_modules(
        repo_path, cert, evidence_root / "_statements", timeout=timeout
    )
    diagnostics: list[str] = []
    if statements_root is None:
        diagnostics.append(
            "scripts/ingest_cert.py could not regenerate statements for this "
            "certificate; no atom was attempted (no_trusted_statement)."
        )
    outcomes: list[AiProofAtomOutcome] = []
    proved_records: dict[str, dict[str, Any]] = {}
    log_parts: list[str] = []

    for atom in unknown_atoms:
        name = atom["name"]
        # Per-run module name: concurrent repairs sharing one checkout must
        # never write / build / delete the same Lean file.
        module = f"{ai_proof_module_for(name)}_{run_tag}"
        theorem_name = f"{name}_correct"
        outcome = AiProofAtomOutcome(
            name=name, proved=False, module=module, theorem=theorem_name
        )
        feedback: list[dict[str, Any]] = []
        module_path = ai_proof_module_path(repo_path, module)
        atom_evidence = evidence_root / (
            f"{sanitize_lean_module_name(name)}_"
            f"{hashlib.sha256(name.encode('utf-8')).hexdigest()[:8]}"
        )
        if name in ambiguous:
            # Promotion is keyed by atom name; two unknown atoms sharing a
            # name cannot be told apart, so neither may be upgraded.
            outcome.error_code = "ambiguous_atom_name"
            outcomes.append(outcome)
            continue
        statement = (
            find_trusted_statement(
                repo_path,
                name,
                theorem_name=theorem_name,
                module_key=bridge_module_key_for(cert, atom),
                generated_root=statements_root,
            )
            if statements_root is not None
            else None
        )
        if statement is None:
            outcome.error_code = "no_trusted_statement"
            outcomes.append(outcome)
            continue
        for attempt in range(1, max_attempts + 1):
            request = build_ai_proof_request(
                atom,
                module=module,
                theorem_name=theorem_name,
                escalation_bundle=escalation_bundle,
                feedback=feedback,
                statement=statement,
            )
            try:
                raw = generator.generate_lean_proof(request)
            except Exception as exc:  # noqa: BLE001 - LLM failures degrade to "not proved"
                logger.warning("ai proof generation failed for %s: %s", name, exc)
                outcome.attempts.append(
                    AiProofAttempt(
                        attempt=attempt,
                        accepted=False,
                        error_code="generator_error",
                        source_path=None,
                        log_path=None,
                        rejection_reason=str(exc),
                    )
                )
                outcome.error_code = "generator_error"
                feedback.append(
                    {
                        "attempt": attempt,
                        "error_code": "generator_error",
                        "log_tail": "",
                    }
                )
                continue
            tactics = extract_tactic_script(raw, theorem_name)
            atom_evidence.mkdir(parents=True, exist_ok=True)
            source_path = atom_evidence / f"attempt_{attempt}.lean"
            log_path = atom_evidence / f"attempt_{attempt}.log"
            (atom_evidence / f"attempt_{attempt}.reply.txt").write_text(
                raw, encoding="utf-8"
            )
            rejection = reject_unsound_lean_source(tactics, theorem_name)
            source = assemble_ai_module(
                statement,
                module=module,
                tactics=tactics or "skip",
                nonce=f"{run_id}/{attempt}",
            )
            source_path.write_text(source, encoding="utf-8")
            if rejection is not None:
                log_path.write_text(f"rejected before lake: {rejection}\n", encoding="utf-8")
                outcome.attempts.append(
                    AiProofAttempt(
                        attempt=attempt,
                        accepted=False,
                        error_code="unsound_source",
                        source_path=str(source_path),
                        log_path=str(log_path),
                        rejection_reason=rejection,
                    )
                )
                outcome.error_code = "unsound_source"
                feedback.append(
                    {
                        "attempt": attempt,
                        "rejection_reason": rejection,
                        "error_code": "unsound_source",
                    }
                )
                continue

            module_path.parent.mkdir(parents=True, exist_ok=True)
            module_path.write_text(source, encoding="utf-8")
            try:
                returncode, log = _lake_build_module(
                    repo_path, module, timeout=timeout
                )
                try:
                    compiled = module_path.read_text(encoding="utf-8")
                except OSError:
                    compiled = None
            finally:
                try:
                    module_path.unlink()
                except OSError:
                    pass
            log_path.write_text(log, encoding="utf-8")
            log_parts.append(f"[{module} attempt {attempt}]\n{log}")
            accepted, error_code = _build_log_accepts(
                returncode, log, theorem_name=theorem_name, module=module
            )
            if accepted and compiled != source:
                # The file Lake compiled is not the evidence we recorded.
                accepted, error_code = False, "source_mismatch"
            outcome.attempts.append(
                AiProofAttempt(
                    attempt=attempt,
                    accepted=accepted,
                    error_code=error_code,
                    source_path=str(source_path),
                    log_path=str(log_path),
                )
            )
            if accepted:
                outcome.proved = True
                outcome.error_code = None
                proved_records[name] = _ai_proof_atom_record(
                    atom,
                    module=module,
                    theorem_name=theorem_name,
                    attempts=attempt,
                    source_path=str(source_path),
                    log_path=str(log_path),
                    bridge_contract=bridge_contract,
                    statement_path=statement.source_path,
                )
                break
            outcome.error_code = error_code
            feedback.append(
                {
                    "attempt": attempt,
                    "error_code": error_code,
                    "log_tail": _tail(_redact_log(log, repo_path)),
                }
            )
            if error_code in {"lake_missing", "timeout"}:
                break
        outcomes.append(outcome)

    proved_names = set(proved_records)
    lean_cert = _upgrade_atoms_by_name(
        cert,
        proved_names,
        strategy=AI_PROOF_STRATEGY,
        lean_atom_records=proved_records,
    )
    complete = all(o.proved for o in outcomes)
    failed = [o for o in outcomes if not o.proved]
    annotate_residual_atoms(lean_cert, [o.to_dict() for o in failed])
    error_code = None
    if not complete:
        error_code = next((o.error_code for o in failed if o.error_code), "tactic_failed")
    diagnostics.append(
        f"AI proof generation proved {len(proved_names)}/{len(outcomes)} "
        "residual unknown atom(s) after Lake verification."
    )
    if failed:
        diagnostics.append(
            "Residual atoms for human review: "
            + ", ".join(sorted(o.name for o in failed))
        )
    return _result(
        success=complete,
        returncode=0 if complete else 1,
        lean_cert=lean_cert,
        stdout="\n".join(log_parts),
        error_code=error_code,
        diagnostics=diagnostics,
        duration_seconds=time.monotonic() - started,
        retryable=False,
        extra={
            "fallback_strategy": AI_PROOF_STRATEGY,
            "partial_success": bool(proved_names) and not complete,
            "ai_proof_used": bool(proved_names),
            "ai_proof_proved": len(proved_names),
            "ai_proof_attempted": len(outcomes),
            "ai_proof_outcomes": [o.to_dict() for o in outcomes],
            "ai_proof_residual": sorted(o.name for o in failed),
            "evidence_dir": str(evidence_root),
        },
    )


def load_escalation_bundle(path: str | Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    return _load_json_file(path)
