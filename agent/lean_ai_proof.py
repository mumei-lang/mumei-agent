"""Task 2-D — AI-generated Lean proofs for residual ``unknown`` atoms.

This module sits *after* the Task 2-C bridge (generated-module path and
known witness modules) and *before* human review.  For every atom that is
still ``z3_check_result == "unknown"`` it asks an LLM to write a Lean 4
module containing ``theorem <atom>_correct``, builds that module with
``lake build`` inside the configured ``mumei-lean`` checkout, and feeds the
build log back to the LLM for repair up to a bounded number of attempts.

Soundness contract
------------------

* An atom is promoted to ``lean_verified`` **only** when Lake compiles the
  AI-written module with exit code 0, no ``error:`` lines and no
  ``declaration uses 'sorry'`` warning.  The LLM output itself is never
  trusted.
* Modules that contain ``sorry`` / ``admit`` / ``axiom`` / ``unsafe`` /
  ``implemented_by`` / ``extern`` are rejected before they reach Lake.
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
_ERROR_LINE_RE = re.compile(r"(^|\n)[^\n]*\berror\b", re.IGNORECASE)
_FORBIDDEN_TOKENS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("sorry", re.compile(r"\bsorry\b")),
    ("admit", re.compile(r"\badmit\b")),
    ("axiom", re.compile(r"^\s*(?:noncomputable\s+)?axiom\b", re.MULTILINE)),
    ("unsafe", re.compile(r"\bunsafe\b")),
    ("implemented_by", re.compile(r"implemented_by")),
    ("extern", re.compile(r"@\[\s*extern")),
    ("native_decide", re.compile(r"\bnative_decide\b")),
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


def reject_unsound_lean_source(source: str, theorem_name: str) -> str | None:
    """Return a rejection reason when *source* must not be sent to Lake."""
    if not source.strip():
        return "empty_source"
    for label, pattern in _FORBIDDEN_TOKENS:
        if pattern.search(source):
            return f"forbidden_token:{label}"
    if not re.search(rf"\btheorem\s+{re.escape(theorem_name)}\b", source):
        return f"missing_theorem:{theorem_name}"
    return None


def build_ai_proof_request(
    atom: dict[str, Any],
    *,
    module: str,
    theorem_name: str,
    escalation_bundle: dict[str, Any] | None,
    feedback: list[dict[str, Any]],
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
    }


def render_ai_proof_prompt(request: dict[str, Any]) -> str:
    atom = request["atom"]
    lines = [
        (
            "Write a complete, self-contained Lean 4 module (Mathlib available) "
            "that states and proves the correctness theorem for a Mumei atom."
        ),
        "",
        (
            f"The module MUST be named `{request['module']}` "
            f"(open with `namespace {request['module']}` after the imports) "
            f"and MUST contain `theorem {request['theorem_name']}`."
        ),
        "Start with `import MumeiLean` (add Mathlib imports as needed).",
        (
            "Do NOT use `sorry`, `admit`, `axiom`, `unsafe`, `native_decide`, "
            "or `implemented_by`; the proof must fully elaborate under `lake build`."
        ),
        "Model Mumei i64 values as `Int` unless the contract needs bounds.",
        "",
        "Mumei atom contract:",
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
    lines += ["", "Return ONLY the Lean source, in a single ```lean code block."]
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
                        "only complete Lean modules whose proofs fully elaborate."
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


def _build_log_accepts(returncode: int, log: str) -> tuple[bool, str | None]:
    if returncode != 0:
        error_code, _ = _classify_bridge_failure(
            stdout=log, stderr="", returncode=returncode
        )
        return False, error_code or "bridge_failed"
    if _SORRY_RE.search(log):
        return False, "tactic_failed"
    if _ERROR_LINE_RE.search(log):
        return False, "bridge_failed"
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
    evidence_root = (
        Path(evidence_dir)
        if evidence_dir is not None
        else repo_path / ".ai_proof_evidence"
    )
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
        for attempt in range(1, max(1, max_attempts) + 1):
            request = build_ai_proof_request(
                atom,
                module=module,
                theorem_name=theorem_name,
                escalation_bundle=escalation_bundle,
                feedback=feedback,
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
            source = extract_lean_source(raw)
            atom_evidence.mkdir(parents=True, exist_ok=True)
            source_path = atom_evidence / f"attempt_{attempt}.lean"
            log_path = atom_evidence / f"attempt_{attempt}.log"
            source_path.write_text(source, encoding="utf-8")
            rejection = reject_unsound_lean_source(source, theorem_name)
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
            accepted, error_code = _build_log_accepts(returncode, log)
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
    all_names = {atom["name"] for atom in unknown_atoms}
    complete = all_names.issubset(proved_names)
    failed = [o for o in outcomes if not o.proved]
    error_code = None
    if not complete:
        error_code = next((o.error_code for o in failed if o.error_code), "tactic_failed")
    diagnostics = [
        (
            f"AI proof generation proved {len(proved_names)}/{len(all_names)} "
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
            "ai_proof_attempted": len(all_names),
            "ai_proof_outcomes": [o.to_dict() for o in outcomes],
            "ai_proof_residual": sorted(o.name for o in failed),
            "evidence_dir": str(evidence_root),
        },
    )


def load_escalation_bundle(path: str | Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    return _load_json_file(path)
