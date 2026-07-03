"""Helper utilities for the Lean bridge."""
from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

from agent.proofcert import (
    VerificationStatus,
    Z3CheckResult,
    iter_atoms,
)

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
