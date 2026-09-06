"""Task 2-D — AI-generated Lean proofs for residual ``unknown`` atoms.

This module sits *after* the Task 2-C bridge (generated-module path and
known witness modules) and *before* human review.  For every atom that is
still ``z3_check_result == "unknown"`` it asks an LLM to write a Lean 4
module containing ``theorem <atom>_correct``, builds that module with
``lake build`` inside the configured ``mumei-lean`` checkout, and feeds the
build log back to the LLM for repair up to a bounded number of attempts.

Soundness contract
------------------

* The theorem *statement* is never written by the LLM.  It is taken
  verbatim from the module ``scripts/bridge.py`` generated for the atom
  (``<mumei-lean>/generated/Generated/**.lean``), i.e. from the trusted
  translator.  The LLM supplies only the tactic script after ``:= by``;
  atoms without a bridge-generated statement are skipped
  (``no_trusted_statement``) and stay ``unknown``.
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

import json
import logging
import re
import shutil
import subprocess
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


def find_trusted_statement(
    repo_path: Path,
    atom_name: str,
    *,
    theorem_name: str,
) -> TrustedStatement | None:
    """Locate ``theorem <theorem_name>`` in the bridge-generated module tree.

    Searches ``<repo>/generated/Generated/**/*.lean`` (skipping the AI
    module directory) and returns the statement header, the module's
    non-theorem declarations (imports / ``open`` / helper ``def``s) and
    its namespace.  ``None`` when the translator never produced a
    statement for the atom (``partial_translation`` etc.).
    """
    root = repo_path / "generated" / AI_PROOF_MODULE_ROOT.split(".")[0]
    if not root.is_dir():
        return None
    ai_root = ai_proof_module_path(repo_path, AI_PROOF_MODULE_ROOT).with_suffix("")
    for candidate in sorted(root.rglob("*.lean")):
        if ai_root in candidate.parents or candidate == ai_root:
            continue
        try:
            text = candidate.read_text(encoding="utf-8")
        except OSError:
            continue
        if not re.search(rf"\btheorem\s+{re.escape(theorem_name)}\b", text):
            continue
        statement = _lift_statement(text, theorem_name, str(candidate))
        if statement is not None:
            return statement
    return None


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


def _audit_axioms(log: str, theorem_name: str) -> str | None:
    """Return an error code unless ``#print axioms`` reports only ALLOWED_AXIOMS."""
    for match in _NO_AXIOMS_RE.finditer(log):
        if match.group("decl").endswith(theorem_name):
            return None
    for match in _AXIOMS_RE.finditer(log):
        if not match.group("decl").endswith(theorem_name):
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
    returncode: int, log: str, *, theorem_name: str | None = None
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
        audit = _audit_axioms(log, theorem_name)
        if audit is not None:
            return False, audit
    return True, None


def _tail(text: str, limit: int = 2000) -> str:
    return text[-limit:] if len(text) > limit else text


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
    run_id = f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:8]}"
    evidence_root = (
        Path(evidence_dir)
        if evidence_dir is not None
        else repo_path / ".ai_proof_evidence"
    ) / run_id
    bridge_contract = _mumei_lean_bridge_contract(repo_path)
    started = time.monotonic()
    outcomes: list[AiProofAtomOutcome] = []
    proved_records: dict[str, dict[str, Any]] = {}
    log_parts: list[str] = []

    for atom in unknown_atoms:
        name = atom["name"]
        module = ai_proof_module_for(name)
        theorem_name = f"{name}_correct"
        outcome = AiProofAtomOutcome(
            name=name, proved=False, module=module, theorem=theorem_name
        )
        feedback: list[dict[str, Any]] = []
        module_path = ai_proof_module_path(repo_path, module)
        atom_evidence = evidence_root / sanitize_lean_module_name(name)
        if name in ambiguous:
            # Promotion is keyed by atom name; two unknown atoms sharing a
            # name cannot be told apart, so neither may be upgraded.
            outcome.error_code = "ambiguous_atom_name"
            outcomes.append(outcome)
            continue
        statement = find_trusted_statement(repo_path, name, theorem_name=theorem_name)
        if statement is None:
            outcome.error_code = "no_trusted_statement"
            outcomes.append(outcome)
            continue
        for attempt in range(1, max(1, max_attempts) + 1):
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
                break
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
            finally:
                try:
                    module_path.unlink()
                except OSError:
                    pass
            log_path.write_text(log, encoding="utf-8")
            log_parts.append(f"[{module} attempt {attempt}]\n{log}")
            accepted, error_code = _build_log_accepts(
                returncode, log, theorem_name=theorem_name
            )
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
                {"attempt": attempt, "error_code": error_code, "log_tail": _tail(log)}
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
    error_code = None
    if not complete:
        error_code = next((o.error_code for o in failed if o.error_code), "tactic_failed")
    diagnostics = [
        (
            f"AI proof generation proved {len(proved_names)}/{len(outcomes)} "
            "residual unknown atom(s) after Lake verification."
        )
    ]
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
