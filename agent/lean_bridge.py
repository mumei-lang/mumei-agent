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

logger = logging.getLogger(__name__)


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
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "success": success,
        "returncode": returncode,
        "lean_cert_path": lean_cert_path,
        "lean_cert": lean_cert,
        "stdout": stdout,
        "stderr": stderr,
        "error_code": error_code,
        "diagnostics": diagnostics or [],
    }
    if duration_seconds is not None:
        payload["duration_seconds"] = duration_seconds
    return payload


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

    atoms: list[dict[str, Any]] = []

    def _consume_cert(cert: dict[str, Any]) -> None:
        cert_atoms = cert.get("atoms")
        if isinstance(cert_atoms, list):
            for atom in cert_atoms:
                if (
                    isinstance(atom, dict)
                    and atom.get("z3_check_result") == "unknown"
                ):
                    atoms.append(atom)
        modules = cert.get("modules")
        if isinstance(modules, dict):
            for module_cert in modules.values():
                if isinstance(module_cert, dict):
                    _consume_cert(module_cert)

    # Direct certificate.
    _consume_cert(verify_result)
    # Common wrappers used by ``MumeiClient.verify`` and the proliferate
    # output JSON.
    for key in ("certificate", "report", "proof_certificate"):
        nested = verify_result.get(key)
        if isinstance(nested, dict):
            _consume_cert(nested)

    return atoms


def run_lean_bridge(
    cert_path: str | Path,
    lean_cert_out: str | Path,
    mumei_lean_repo: str | Path,
    *,
    no_build: bool = False,
    timeout: float | None = 600.0,
) -> dict[str, Any]:
    """Invoke ``mumei-lean``'s ``scripts/bridge.py`` as a subprocess.

    Parameters
    ----------
    cert_path:
        Path to the input mumei ``.proof-cert.json``.
    lean_cert_out:
        Path where ``bridge.py`` should write the upgraded
        ``.lean-cert.json``.  Created lazily by ``bridge.py``.
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
    cmd: list[str] = [
        sys.executable,
        str(bridge_script),
        "--cert",
        str(cert_path),
        "--lean-cert-out",
        str(lean_cert_out),
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
        return _result(
            success=False,
            returncode=-1,
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
    out_path = Path(lean_cert_out)
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

    return _result(
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
    upgraded: dict[str, Any] = json.loads(json.dumps(original_cert))

    proved_names: set[str] = set()
    if isinstance(lean_cert, dict):
        for atom in lean_cert.get("atoms", []) or []:
            if (
                isinstance(atom, dict)
                and atom.get("z3_check_result") == "lean_verified"
                and isinstance(atom.get("name"), str)
            ):
                proved_names.add(atom["name"])

    atoms = upgraded.get("atoms")
    if isinstance(atoms, list):
        for atom in atoms:
            if (
                isinstance(atom, dict)
                and atom.get("name") in proved_names
                and atom.get("z3_check_result") != "lean_verified"
            ):
                atom["z3_check_result"] = "lean_verified"
                atom["status"] = "verified"
        if atoms:
            upgraded["all_verified"] = all(
                isinstance(a, dict)
                and a.get("z3_check_result") in {"unsat", "lean_verified"}
                for a in atoms
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
    discoverable.
    """
    if not mumei_lean_repo:
        return False
    repo_path = Path(mumei_lean_repo)
    if not repo_path.exists():
        return False
    if not (repo_path / "scripts" / "bridge.py").exists():
        return False
    return shutil.which(sys.executable) is not None
