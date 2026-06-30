"""Task 2-C — mumei-lean fallback helpers.

Glue layer that lets ``agent.proliferate`` opt-in to delegating
``z3_check_result == "unknown"`` atoms to the
`mumei-lang/mumei-lean <https://github.com/mumei-lang/mumei-lean>`_
Lean 4 proof backend after the main forge / verify cycle.

The integration is deliberately external:

* :func:`extract_unknown_atoms` walks a mumei verify result and pulls
  out every atom that Z3 returned ``unknown`` on, so callers can decide
  whether the run is worth handing off to Lean.
* :func:`run_lean_bridge` invokes the Lean side by shelling out to
  ``python <mumei-lean>/scripts/bridge.py`` from the configured
  ``mumei-lean`` checkout.  Any failure (missing repo, missing
  toolchain, non-zero exit) is reported as a structured dict instead
  of an exception so the outer pipeline can degrade gracefully.
* :func:`merge_lean_cert_into_proof_cert` upgrades the original mumei
  proof certificate with the Lean-discharged atoms — atoms whose
  ``z3_check_result`` is ``"lean_verified"`` after the merge are
  considered proved.

This module never imports from ``mumei-lean``; the bridge is invoked
purely as a subprocess so the agent's runtime dependencies stay light.
"""
from __future__ import annotations

import ast
import json
import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from agent.proofcert import (
    VerificationStatus,
    Z3CheckResult,
    iter_atoms,
)

logger = logging.getLogger(__name__)

_RETRYABLE_ERROR_CODES = {
    "bridge_failed",
    "import_error",
    "lake_missing",
    "subprocess_error",
    "timeout",
}

_NON_RETRYABLE_ERROR_CODES = {
    "bridge_missing",
    "partial_translation",
    "repo_missing",
    "tactic_failed",
    "theorem_not_found",
}

_KNOWN_LEAN_WITNESSES: dict[str, dict[str, str]] = {
    "abs_saturating": {
        "module_key": "std/math/abs",
        "module": "MumeiLean.StdMathAbs",
        "theorem": "abs_saturating_correct",
    },
    "fixed_point_abs": {
        "module_key": "std/math/fixed_point",
        "module": "MumeiLean.StdMathAbs",
        "theorem": "fixed_point_abs_correct",
    },
    "fixed_point_from_int": {
        "module_key": "std/math/fixed_point",
        "module": "MumeiLean.StdMathAbs",
        "theorem": "fixed_point_from_int_correct",
    },
    "list_length": {
        "module_key": "std/list",
        "module": "MumeiLean.StdMathAbs",
        "theorem": "list_length_correct",
    },
    "balance_conservation": {
        "module_key": "std/finance/settlement",
        "module": "MumeiLean.Settlement",
        "theorem": "balance_conservation",
    },
    "trace_balance_conservation": {
        "module_key": "std/finance/settlement",
        "module": "MumeiLean.Settlement",
        "theorem": "trace_balance_conservation",
    },
    "no_settlement_without_validate": {
        "module_key": "std/finance/settlement",
        "module": "MumeiLean.Settlement",
        "theorem": "no_settlement_without_validate",
    },
    "no_reentrancy_after_withdraw": {
        "module_key": "std/contract/vault",
        "module": "MumeiLean.SmartContract",
        "theorem": "no_reentrancy_after_withdraw",
    },
    "withdraw_preserves_other_balance": {
        "module_key": "std/contract/vault",
        "module": "MumeiLean.SmartContract",
        "theorem": "withdraw_preserves_other_balance",
    },
    "withdraw_amount_nonnegative_bound": {
        "module_key": "std/contract/vault",
        "module": "MumeiLean.SmartContract",
        "theorem": "withdraw_amount_nonnegative_bound",
    },
    "nlae_vault_withdraw_amount_nonnegative_bound": {
        "module_key": "examples/nlae_integration_demo",
        "module": "MumeiLean.SmartContract",
        "theorem": "nlae_vault_withdraw_amount_nonnegative_bound",
    },
    "nlae_vault_no_negative_withdraw": {
        "module_key": "examples/nlae_integration_demo",
        "module": "MumeiLean.SmartContract",
        "theorem": "nlae_vault_no_negative_withdraw",
    },
    "add_bounded": {
        "module_key": "std/math/patterns",
        "module": "MumeiLean.Patterns",
        "theorem": "add_bounded",
    },
    "transfer_preserves_sum": {
        "module_key": "std/math/patterns",
        "module": "MumeiLean.Patterns",
        "theorem": "transfer_preserves_sum",
    },
}


def _result(
    *,
    success: bool,
    returncode: int,
    lean_cert_path: str | None = None,
    lean_cert: dict[str, Any] | None = None,
    stdout: str = "",
    stderr: str = "",
    error_code: str | None = None,
    diagnostics: list[str] | None = None,
    duration_seconds: float | None = None,
    retryable: bool | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if retryable is None:
        retryable = is_bridge_failure_retryable(error_code)
    payload: dict[str, Any] = {
        "success": success,
        "returncode": returncode,
        "lean_cert_path": lean_cert_path,
        "lean_cert": lean_cert,
        "stdout": stdout,
        "stderr": stderr,
        "error_code": error_code,
        "diagnostics": diagnostics or [],
        "retryable": retryable,
    }
    if duration_seconds is not None:
        payload["duration_seconds"] = duration_seconds
    if extra:
        payload.update(extra)
    return payload


def is_bridge_failure_retryable(error_code: str | None) -> bool:
    """Return whether retrying can plausibly change a bridge failure."""
    if error_code is None:
        return False
    if error_code in _RETRYABLE_ERROR_CODES:
        return True
    if error_code in _NON_RETRYABLE_ERROR_CODES:
        return False
    return False


def _coerce_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _classify_bridge_failure(
    *,
    stdout: str,
    stderr: str,
    returncode: int,
) -> tuple[str | None, list[str]]:
    combined = f"{stdout}\n{stderr}".lower()
    diagnostics: list[str] = []
    error_code: str | None = None

    if returncode == 0:
        return None, diagnostics

    if (
        "lake" in combined
        and (
            "not found" in combined
            or "no such file" in combined
            or "command not found" in combined
        )
    ):
        error_code = "lake_missing"
        diagnostics.append(
            "lake is not available to the bridge; install elan/Lean and ensure "
            "$HOME/.elan/bin is on PATH."
        )
    elif (
        "invalid 'import' command" in combined
        or "invalid import command" in combined
        or "failed to import" in combined
        or "cannot find module" in combined
        or "unknown module" in combined
        or (
            ".olean" in combined
            and ("does not exist" in combined or "no such file" in combined)
        )
    ):
        error_code = "import_error"
        diagnostics.append(
            "Lean could not resolve an import or generated module; retry after "
            "refreshing Lake/mathlib caches or regenerating Generated modules."
        )
    elif (
        "unknown constant" in combined
        or "unknown declaration" in combined
        or "unknown identifier" in combined
        or "declaration has not been declared" in combined
        or "theorem not found" in combined
    ):
        error_code = "theorem_not_found"
        diagnostics.append(
            "Lean could not find a referenced theorem; check that the expected "
            "witness module is imported and that theorem names match atom names."
        )
    elif (
        "unsolved goals" in combined
        or "tactic failed" in combined
        or "omega could not" in combined
        or "simp made no progress" in combined
        or "proof search failed" in combined
        or ("mumei_arith" in combined and "failed" in combined)
    ):
        error_code = "tactic_failed"
        diagnostics.append(
            "Lean reached theorem elaboration but the selected tactic did not "
            "close all goals; try a stronger handwritten witness or proof strategy."
        )
    elif (
        "partial_translation" in combined
        or "partial translation" in combined
        or "manual_review" in combined
        or "unsupported syntax" in combined
        or "unsupported expression" in combined
    ):
        error_code = "partial_translation"
        diagnostics.append(
            "mumei-lean emitted a partial translation; inspect the generated Lean "
            "module for unsupported Mumei syntax or manual_review atoms."
        )
    else:
        error_code = "bridge_failed"
        diagnostics.append(
            "mumei-lean bridge exited non-zero; inspect stdout/stderr for the "
            "Lean theorem or Lake build that failed."
        )

    return error_code, diagnostics


def extract_unknown_atoms(verify_result: dict[str, Any]) -> list[dict[str, Any]]:
    """Return atoms with ``z3_check_result == "unknown"`` from *verify_result*.

    *verify_result* may be either a single mumei proof certificate
    (i.e. a dict with an ``"atoms"`` list) or a wrapper dict that
    embeds the certificate under ``"certificate"`` / ``"report"``.
    Bundle-style payloads with a ``"modules"`` mapping are flattened
    so callers do not need to know which shape mumei emitted.
    """
    if not isinstance(verify_result, dict):
        return []
    return [
        atom.raw
        for atom in iter_atoms(verify_result, include_candidates=False)
        if atom.z3_check_result == Z3CheckResult.UNKNOWN
    ]


def _load_json_file(path: str | Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _default_lean_cert_out(
    input_path: Path,
    *,
    escalation_bundle: bool,
) -> Path:
    name = input_path.name
    if escalation_bundle:
        suffix = ".escalation-bundle.json"
    else:
        suffix = ".proof-cert.json"

    if name.endswith(suffix):
        stem = name[: -len(suffix)]
    elif name.endswith(".json"):
        stem = name[: -len(".json")]
    else:
        stem = input_path.stem
    return input_path.with_name(f"{stem}.lean-cert.json")


def _module_source_path(repo_path: Path, module: str) -> Path:
    return repo_path / Path(*module.split(".")).with_suffix(".lean")


def _atom_names_with_result(cert: dict[str, Any], result: str) -> set[str]:
    return {
        atom.name
        for atom in iter_atoms(cert)
        if atom.z3_check_result == result and atom.name is not None
    }


def _lean_atom_records_with_result(
    cert: dict[str, Any],
    result: str,
) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for atom in iter_atoms(cert):
        if atom.z3_check_result == result and atom.name is not None:
            records[atom.name] = atom.raw
    return records


def _upgrade_atoms_by_name(
    cert: dict[str, Any],
    proved_names: set[str],
    *,
    strategy: str | None = None,
    lean_atom_records: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    upgraded: dict[str, Any] = json.loads(json.dumps(cert))

    for atom in iter_atoms(upgraded):
        if (
            atom.name in proved_names
            and atom.z3_check_result == Z3CheckResult.UNKNOWN
        ):
            atom.raw["z3_check_result"] = Z3CheckResult.LEAN_VERIFIED.value
            atom.raw["status"] = VerificationStatus.VERIFIED.value
            lean_atom = (lean_atom_records or {}).get(str(atom.name))
            if isinstance(lean_atom, dict):
                for field in (
                    "translator_version",
                    "bridge_lemma_hash",
                    "lean_metadata",
                    "lean_result_metadata",
                    "unknown_obligation_domain",
                    "escalation_reason",
                ):
                    if field in lean_atom:
                        atom.raw[field] = json.loads(json.dumps(lean_atom[field]))
            if strategy is not None:
                atom.raw["lean_fallback_strategy"] = strategy

    def _refresh_all_verified(payload: dict[str, Any]) -> None:
        atoms = payload.get("atoms")
        if isinstance(atoms, list):
            payload["all_verified"] = all(
                isinstance(atom, dict)
                and atom.get("z3_check_result")
                in {
                    Z3CheckResult.UNSAT.value,
                    Z3CheckResult.LEAN_VERIFIED.value,
                }
                for atom in atoms
            )
        modules = payload.get("modules")
        if isinstance(modules, dict):
            for module_cert in modules.values():
                if isinstance(module_cert, dict):
                    _refresh_all_verified(module_cert)

    _refresh_all_verified(upgraded)
    return upgraded


def _unknowns_verified_in_cert(
    original_cert: dict[str, Any] | None,
    upgraded_cert: dict[str, Any] | None,
) -> tuple[bool, bool]:
    if original_cert is None or upgraded_cert is None:
        return False, False
    unknown_names = _atom_names_with_result(original_cert, Z3CheckResult.UNKNOWN)
    if not unknown_names:
        return False, False
    verified_names = _atom_names_with_result(
        upgraded_cert, Z3CheckResult.LEAN_VERIFIED
    )
    proved_any = bool(unknown_names.intersection(verified_names))
    proved_all = unknown_names.issubset(verified_names)
    return proved_all, proved_any and not proved_all


def count_lean_verified_unknowns(
    original_cert: dict[str, Any],
    upgraded_cert: dict[str, Any],
) -> int:
    """Count original Z3-unknown atoms promoted to ``lean_verified``."""
    unknown_names = _atom_names_with_result(original_cert, Z3CheckResult.UNKNOWN)
    verified_names = _atom_names_with_result(
        upgraded_cert, Z3CheckResult.LEAN_VERIFIED
    )
    return len(unknown_names.intersection(verified_names))


def _matches_known_witness(atom: dict[str, Any]) -> bool:
    name = atom.get("name")
    if not isinstance(name, str):
        return False
    witness = _KNOWN_LEAN_WITNESSES.get(name)
    if witness is None:
        return False
    module_key = atom.get("module_key")
    return not isinstance(module_key, str) or module_key == witness["module_key"]


def _mumei_lean_bridge_contract(
    mumei_lean_repo: str | Path,
) -> dict[str, str]:
    repo_path = Path(mumei_lean_repo)
    contract: dict[str, str] = {}
    for relative in ("scripts/export_cert.py", "scripts/expr_translator.py"):
        path = repo_path / relative
        if not path.exists():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            stripped = line.strip()
            for key in ("TRANSLATOR_VERSION", "BRIDGE_LEMMA_HASH"):
                prefix = f"{key} = "
                if not stripped.startswith(prefix):
                    continue
                try:
                    value = ast.literal_eval(stripped[len(prefix) :])
                except (SyntaxError, ValueError):
                    continue
                if isinstance(value, str):
                    contract[key] = value
        if {
            "TRANSLATOR_VERSION",
            "BRIDGE_LEMMA_HASH",
        }.issubset(contract):
            break
    return contract


def _known_witness_atom_records(
    cert: dict[str, Any],
    witness_names: set[str],
    *,
    mumei_lean_repo: str | Path,
) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    bridge_contract = _mumei_lean_bridge_contract(mumei_lean_repo)

    def _record_for_atom(atom: dict[str, Any]) -> dict[str, Any] | None:
        name = atom.get("name")
        if not isinstance(name, str) or name not in witness_names:
            return None
        witness = _KNOWN_LEAN_WITNESSES.get(name)
        if witness is None:
            return None

        existing_metadata = atom.get("lean_metadata")
        metadata = (
            dict(existing_metadata)
            if isinstance(existing_metadata, dict)
            else {}
        )
        existing_diagnostics = metadata.get("diagnostics")
        diagnostics = (
            list(existing_diagnostics)
            if isinstance(existing_diagnostics, list)
            else []
        )
        if "known_witness_module" not in diagnostics:
            diagnostics.append("known_witness_module")
        metadata.update(
            {
                "status": "lean_verified",
                "theorem_name": witness["theorem"],
                "lean_module": witness["module"],
                "lean_theorem_name": witness["theorem"],
                "known_witness_used": True,
                "proof_path": str(
                    Path(*witness["module"].split("."))
                    .with_suffix(".lean")
                    .as_posix()
                ),
                "diagnostics": diagnostics,
                "proof_strategy": {
                    "strategy": "known_witness_module",
                    "module": witness["module"],
                    "theorem": witness["theorem"],
                },
            }
        )
        for source_field, metadata_field in (
            ("z3_result_class", "z3_result_class"),
            ("escalation_reason", "escalation_reason"),
            ("logic_fragment_tag", "logic_fragment_tag"),
            ("logic_fragment_tags", "logic_fragment_tags"),
            ("unknown_obligation_domain", "unknown_obligation_domain"),
        ):
            value = atom.get(source_field)
            if value:
                metadata.setdefault(metadata_field, value)

        record = json.loads(json.dumps(atom))
        record["z3_check_result"] = Z3CheckResult.LEAN_VERIFIED.value
        record["status"] = VerificationStatus.VERIFIED.value
        for const_key, field in (
            ("TRANSLATOR_VERSION", "translator_version"),
            ("BRIDGE_LEMMA_HASH", "bridge_lemma_hash"),
        ):
            value = bridge_contract.get(const_key)
            if value:
                record[field] = value
                metadata[field] = value
            elif isinstance(atom.get(field), str):
                record[field] = atom[field]
                metadata.setdefault(field, atom[field])
        record["lean_metadata"] = metadata
        record["lean_result_metadata"] = {
            "fallback_strategy": "known_witness_module",
            "known_witness_used": True,
        }
        return record

    for atom in iter_atoms(cert):
        record = _record_for_atom(atom.raw)
        if record is not None:
            records[record["name"]] = record
    return records


def _verify_known_witnesses(
    *,
    cert_path: str | Path,
    mumei_lean_repo: str | Path,
    timeout: float | None,
) -> dict[str, Any] | None:
    cert = _load_json_file(cert_path)
    if cert is None:
        return None
    unknown_atoms = extract_unknown_atoms(cert)
    atom_names = {
        atom["name"]
        for atom in unknown_atoms
        if isinstance(atom.get("name"), str)
    }
    witness_names = {
        atom["name"] for atom in unknown_atoms if _matches_known_witness(atom)
    }
    if not witness_names:
        return None

    repo_path = Path(mumei_lean_repo)
    modules = {
        _KNOWN_LEAN_WITNESSES[name]["module"] for name in witness_names
    }
    diagnostics: list[str] = []
    missing_witnesses: list[str] = []
    for name in sorted(witness_names):
        witness = _KNOWN_LEAN_WITNESSES[name]
        src = _module_source_path(repo_path, witness["module"])
        try:
            source_text = src.read_text(encoding="utf-8")
        except OSError:
            missing_witnesses.append(f"{name}:{src}")
            continue
        if f"theorem {witness['theorem']}" not in source_text:
            missing_witnesses.append(f"{name}:{witness['theorem']}")
    if missing_witnesses:
        return _result(
            success=False,
            returncode=-1,
            stderr="known Lean witness missing: " + ", ".join(missing_witnesses),
            error_code="theorem_not_found",
            diagnostics=[
                "Known std witness fallback could not find every expected theorem."
            ],
            extra={"fallback_strategy": "known_witness_module"},
        )

    if shutil.which("lake") is None:
        return _result(
            success=False,
            returncode=-1,
            stderr="lake not found on PATH",
            error_code="lake_missing",
            diagnostics=[
                "Known std witness fallback requires Lake to type-check witness modules."
            ],
            extra={"fallback_strategy": "known_witness_module"},
        )

    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    started = time.monotonic()
    for module in sorted(modules):
        cmd = ["lake", "build", module]
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            elapsed = time.monotonic() - started
            return _result(
                success=False,
                returncode=-1,
                stdout=_coerce_output(exc.stdout),
                stderr=(
                    f"known witness build timed out after {timeout} seconds\n"
                    f"{_coerce_output(exc.stderr)}"
                ).strip(),
                error_code="timeout",
                diagnostics=[
                    "Lean witness module build exceeded the configured timeout."
                ],
                duration_seconds=elapsed,
                extra={"fallback_strategy": "known_witness_module"},
            )
        stdout_parts.append(proc.stdout)
        stderr_parts.append(proc.stderr)
        if proc.returncode != 0:
            error_code, failure_diagnostics = _classify_bridge_failure(
                stdout=proc.stdout,
                stderr=proc.stderr,
                returncode=proc.returncode,
            )
            return _result(
                success=False,
                returncode=proc.returncode,
                stdout="\n".join(stdout_parts),
                stderr="\n".join(stderr_parts),
                error_code=error_code,
                diagnostics=failure_diagnostics,
                duration_seconds=time.monotonic() - started,
                extra={"fallback_strategy": "known_witness_module"},
            )

    lean_atom_records = _known_witness_atom_records(
        cert,
        set(witness_names),
        mumei_lean_repo=mumei_lean_repo,
    )
    witness_cert = _upgrade_atoms_by_name(
        cert,
        set(witness_names),
        strategy="known_witness_module",
        lean_atom_records=lean_atom_records,
    )

    verified_count = len(witness_names)
    diagnostics.append(
        "Verified known std Lean witness module(s): "
        + ", ".join(sorted(modules))
    )
    complete = atom_names.issubset(witness_names)
    return _result(
        success=complete,
        returncode=0 if complete else 1,
        lean_cert=(
            witness_cert
            if isinstance(witness_cert, dict)
            else {"atoms": []}
        ),
        stdout="\n".join(stdout_parts),
        stderr="\n".join(stderr_parts),
        error_code=None if complete else "theorem_not_found",
        diagnostics=diagnostics,
        duration_seconds=time.monotonic() - started,
        retryable=False,
        extra={
            "fallback_strategy": "known_witness_module",
            "partial_success": not complete and verified_count > 0,
            "known_witness_verified": verified_count,
        },
    )


def _combine_with_witness_fallback(
    *,
    primary: dict[str, Any],
    cert_path: str | Path,
    mumei_lean_repo: str | Path,
    timeout: float | None,
) -> dict[str, Any]:
    witness = _verify_known_witnesses(
        cert_path=cert_path,
        mumei_lean_repo=mumei_lean_repo,
        timeout=timeout,
    )
    if witness is None:
        return primary

    primary_error = primary.get("error_code")
    primary_diagnostics = primary.get("diagnostics")
    if not isinstance(primary_diagnostics, list):
        primary_diagnostics = []
    diagnostics = list(primary_diagnostics)
    witness_diagnostics = witness.get("diagnostics")
    if isinstance(witness_diagnostics, list):
        diagnostics.extend(witness_diagnostics)

    stdout = "\n".join(
        part
        for part in (str(primary.get("stdout", "")), str(witness.get("stdout", "")))
        if part
    )
    stderr = "\n".join(
        part
        for part in (str(primary.get("stderr", "")), str(witness.get("stderr", "")))
        if part
    )
    duration = float(primary.get("duration_seconds") or 0.0) + float(
        witness.get("duration_seconds") or 0.0
    )
    witness_success = bool(witness.get("success"))
    primary_cert = primary.get("lean_cert")
    if not isinstance(primary_cert, dict):
        primary_cert = _load_json_file(cert_path)
    witness_cert = witness.get("lean_cert")
    if isinstance(primary_cert, dict) and isinstance(witness_cert, dict):
        lean_cert: dict[str, Any] | None = merge_lean_cert_into_proof_cert(
            primary_cert,
            witness_cert,
        )
    elif isinstance(witness_cert, dict):
        lean_cert = witness_cert
    elif isinstance(primary_cert, dict):
        lean_cert = primary_cert
    else:
        lean_cert = None
    original_cert = _load_json_file(cert_path)
    combined_success, partial_success = _unknowns_verified_in_cert(
        original_cert,
        lean_cert,
    )
    return _result(
        success=combined_success,
        returncode=0 if combined_success else int(primary.get("returncode", -1)),
        lean_cert_path=None,
        lean_cert=lean_cert,
        stdout=stdout,
        stderr=stderr,
        error_code=(
            None
            if combined_success
            else str(witness.get("error_code") or primary_error)
        ),
        diagnostics=diagnostics,
        duration_seconds=duration,
        retryable=(
            False
            if combined_success
            else bool(primary.get("retryable") or witness.get("retryable"))
        ),
        extra={
            "primary_error_code": primary_error,
            "fallback_strategy": witness.get("fallback_strategy"),
            "partial_success": partial_success,
            "strategy_attempts": [
                {
                    "name": "generated_bridge",
                    "success": bool(primary.get("success")),
                    "error_code": primary_error,
                },
                {
                    "name": "known_witness_module",
                    "success": witness_success,
                    "error_code": witness.get("error_code"),
                    "proved": witness.get("known_witness_verified"),
                },
            ],
        },
    )


def run_lean_bridge(
    cert_path: str | Path | None,
    lean_cert_out: str | Path | None,
    mumei_lean_repo: str | Path,
    *,
    no_build: bool = False,
    timeout: float | None = 600.0,
    enable_known_witness_fallback: bool = True,
    escalation_bundle_path: str | Path | None = None,
) -> dict[str, Any]:
    """Invoke ``mumei-lean``'s ``scripts/bridge.py`` as a subprocess.

    Parameters
    ----------
    cert_path:
        Path to the input mumei ``.proof-cert.json``.  May be
        ``None`` when *escalation_bundle_path* is provided.
    lean_cert_out:
        Path where ``bridge.py`` should write the upgraded
        ``.lean-cert.json``.  When ``None``, derived from the selected
        input path as ``<stem>.lean-cert.json``.
    mumei_lean_repo:
        Filesystem path to a ``mumei-lang/mumei-lean`` checkout.
        Must contain ``scripts/bridge.py`` and ``lakefile.lean``.
    no_build:
        When True, pass ``--no-build`` so ``bridge.py`` only ingests
        the unknown atoms and skips ``lake build``.  Useful for dry
        runs and when the runner has no Lean toolchain installed.
    timeout:
        Maximum seconds to wait for the bridge subprocess.  Defaults
        to 10 minutes; pass ``None`` to disable.
    escalation_bundle_path:
        Path to a mumei ``.escalation-bundle.json`` emitted by
        ``mumei verify --escalate-lean --emit escalation-bundle``.
        When provided, the bridge is invoked with
        ``--escalation-bundle`` instead of ``--cert``.

    Returns
    -------
    A dict with the keys ``success`` (bool), ``returncode`` (int),
    ``lean_cert_path`` (str | None), ``lean_cert`` (dict | None) and
    ``stdout`` / ``stderr`` (str).  The ``lean_cert`` is loaded from
    *lean_cert_out* on success so callers can hand it directly to
    :func:`merge_lean_cert_into_proof_cert`.
    """
    repo_path = Path(mumei_lean_repo)
    if not repo_path.exists():
        return _result(
            success=False,
            returncode=-1,
            stderr=f"mumei_lean_repo does not exist: {repo_path}",
            error_code="repo_missing",
            diagnostics=[
                "Set MUMEI_LEAN_REPO to a mumei-lang/mumei-lean checkout."
            ],
        )
    bridge_script = repo_path / "scripts" / "bridge.py"
    if not bridge_script.exists():
        return _result(
            success=False,
            returncode=-1,
            stderr=f"bridge.py not found at {bridge_script}",
            error_code="bridge_missing",
            diagnostics=[
                "mumei-lean checkout is incomplete; expected scripts/bridge.py."
            ],
        )

    diagnostics: list[str] = []
    if not no_build:
        if shutil.which("lake") is None and (repo_path / "lakefile.lean").exists():
            return _result(
                success=False,
                returncode=-1,
                stderr="lake not found on PATH",
                error_code="lake_missing",
                diagnostics=[
                    "lake is required for Lean build fallback; install elan/Lean "
                    "and ensure $HOME/.elan/bin is on PATH."
                ],
            )
        if not (repo_path / "lakefile.lean").exists():
            diagnostics.append(
                "lakefile.lean not found; bridge.py may be running in a fixture "
                "or an incomplete mumei-lean checkout."
            )

    # Invoke bridge.py directly rather than via ``python -m
    # scripts.bridge`` because ``mumei-lean``'s ``scripts/`` directory
    # is not guaranteed to be a Python package (no ``__init__.py``).
    # Running the file as a script avoids the package-import
    # requirement while still honouring ``cwd=repo_path`` so
    # bridge-relative imports continue to resolve.
    if escalation_bundle_path is not None:
        input_flag = "--escalation-bundle"
        input_path = Path(escalation_bundle_path)
        using_escalation_bundle = True
    elif cert_path is not None:
        input_flag = "--cert"
        input_path = Path(cert_path)
        using_escalation_bundle = False
    else:
        return _result(
            success=False,
            returncode=-1,
            stderr=(
                "cert_path is required unless escalation_bundle_path is provided"
            ),
            error_code="input_missing",
            diagnostics=[
                "Pass a .proof-cert.json via cert_path or an "
                "escalation-bundle via escalation_bundle_path."
            ],
            retryable=False,
        )

    out_path = (
        Path(lean_cert_out)
        if lean_cert_out is not None
        else _default_lean_cert_out(
            input_path,
            escalation_bundle=using_escalation_bundle,
        )
    )
    cmd: list[str] = [
        sys.executable,
        str(bridge_script),
        input_flag,
        str(input_path),
        "--lean-cert-out",
        str(out_path),
    ]
    if no_build:
        cmd.append("--no-build")

    logger.info("lean_bridge: invoking %s", " ".join(cmd))
    started = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        elapsed = time.monotonic() - started
        timeout_result = _result(
            success=False,
            returncode=-1,
            lean_cert_path=str(out_path) if out_path.exists() else None,
            lean_cert=_load_json_file(out_path),
            stdout=_coerce_output(exc.stdout),
            stderr=(
                f"lean_bridge subprocess timed out after {timeout} seconds\n"
                f"{_coerce_output(exc.stderr)}"
            ).strip(),
            error_code="timeout",
            diagnostics=[
                "Lean build exceeded the configured timeout; retry with a warm "
                "Lake cache or increase the bridge timeout for large modules."
            ],
            duration_seconds=elapsed,
        )
        if enable_known_witness_fallback and not no_build:
            return _combine_with_witness_fallback(
                primary=timeout_result,
                cert_path=input_path,
                mumei_lean_repo=mumei_lean_repo,
                timeout=timeout,
            )
        return timeout_result
    except OSError as exc:
        elapsed = time.monotonic() - started
        return _result(
            success=False,
            returncode=-1,
            stderr=f"lean_bridge subprocess failed: {exc}",
            error_code="subprocess_error",
            diagnostics=[
                "Python could not execute mumei-lean/scripts/bridge.py."
            ],
            duration_seconds=elapsed,
        )
    elapsed = time.monotonic() - started

    lean_cert: dict[str, Any] | None = None
    if out_path.exists():
        try:
            lean_cert = json.loads(out_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(
                "lean_bridge: could not parse %s: %s", out_path, exc
            )

    error_code, failure_diagnostics = _classify_bridge_failure(
        stdout=proc.stdout,
        stderr=proc.stderr,
        returncode=proc.returncode,
    )
    diagnostics.extend(failure_diagnostics)

    primary_result = _result(
        success=proc.returncode == 0,
        returncode=proc.returncode,
        lean_cert_path=str(out_path) if lean_cert is not None else None,
        lean_cert=lean_cert,
        stdout=proc.stdout,
        stderr=proc.stderr,
        error_code=error_code,
        diagnostics=diagnostics,
        duration_seconds=elapsed,
    )
    if (
        enable_known_witness_fallback
        and not no_build
        and not primary_result["success"]
    ):
        return _combine_with_witness_fallback(
            primary=primary_result,
            cert_path=input_path,
            mumei_lean_repo=mumei_lean_repo,
            timeout=timeout,
        )
    return primary_result


def merge_lean_cert_into_proof_cert(
    original_cert: dict[str, Any],
    lean_cert: dict[str, Any],
) -> dict[str, Any]:
    """Return *original_cert* upgraded with Lean-verified atom records.

    For every atom in *lean_cert* whose ``z3_check_result`` is
    ``"lean_verified"`` (the marker that ``mumei-lean``'s
    ``scripts/export_cert.py`` writes after a successful ``lake
    build``), the matching atom in *original_cert* (matched by
    ``name``) is upgraded:

    * ``z3_check_result`` becomes ``"lean_verified"``;
    * ``status`` becomes ``"verified"``;
    * any pre-existing fields are preserved verbatim.

    The original certificate is *not* mutated; a deep-copied dict is
    returned so callers can keep both versions side-by-side.

    The function also propagates the top-level ``lean_version`` and
    ``lean_cert_schema_version`` fields (when present in *lean_cert*)
    and recomputes ``all_verified`` over the upgraded atom list.
    """
    lean_atom_records = _lean_atom_records_with_result(
        lean_cert,
        Z3CheckResult.LEAN_VERIFIED.value,
    )
    proved_names = set(lean_atom_records)
    upgraded = _upgrade_atoms_by_name(
        original_cert,
        proved_names,
        lean_atom_records=lean_atom_records,
    )

    if isinstance(lean_cert, dict):
        if "lean_version" in lean_cert:
            upgraded["lean_version"] = lean_cert["lean_version"]
        if "lean_cert_schema_version" in lean_cert:
            upgraded["lean_cert_schema_version"] = lean_cert[
                "lean_cert_schema_version"
            ]

    return upgraded


def lean_fallback_available(mumei_lean_repo: str | Path | None) -> bool:
    """Quick sanity check used by :mod:`agent.proliferate` before opt-in.

    Returns True only when the Lean repo path looks usable and a
    ``python`` interpreter capable of running the bridge module is
    discoverable for proof-certificate and escalation-bundle bridge
    modes.
    """
    if not mumei_lean_repo:
        return False
    repo_path = Path(mumei_lean_repo)
    if not repo_path.exists():
        return False
    if not (repo_path / "scripts" / "bridge.py").exists():
        return False
    return shutil.which(sys.executable) is not None
