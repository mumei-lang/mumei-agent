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

import json
import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from agent.lean_bridge_helpers import (
    _KNOWN_LEAN_WITNESSES,
    _NON_RETRYABLE_ERROR_CODES,
    _RETRYABLE_ERROR_CODES,
    _atom_names_with_result,
    _classify_bridge_failure,
    _coerce_output,
    _default_lean_cert_out,
    _known_witness_atom_records,
    _load_json_file,
    _matches_known_witness,
    _lean_atom_records_with_result,
    _module_source_path,
    _mumei_lean_bridge_contract,
    _result,
    _upgrade_atoms_by_name,
    _unknowns_verified_in_cert,
    count_lean_verified_unknowns,
    extract_unknown_atoms,
    is_bridge_failure_retryable,
    merge_lean_cert_into_proof_cert,
)

logger = logging.getLogger(__name__)

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
