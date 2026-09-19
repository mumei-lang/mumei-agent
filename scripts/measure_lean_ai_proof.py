#!/usr/bin/env python3
"""B-7: produce AI-*on* Lean proof certificates for the mumei evaluation suite.

For every benchmark source under the mumei ``benchmarks/`` tree this script
runs ``mumei verify --proof-cert`` (Z3 only), and for files that leave Z3
``unknown`` atoms behind it runs :func:`agent.lean_bridge.run_lean_bridge`
with the AI proof generator enabled (``--ai-proof on``) or disabled
(``--ai-proof off``).  The merged, upgraded proof certificate is written to
``--cert-dir/<category>/<file>.proof.json`` and consumed by::

    python3 benchmarks/evaluation_suite.py --ai-proof-cert-dir <cert-dir> ...

in the mumei repository, which pairs it with the suite's own AI-off harness
run to report ``lean_verified`` delta, ``ai_proof_used`` atoms and the
remaining ``manual_lemma_reason`` count.  A ``run.json`` manifest records the
LLM model, mumei-lean checkout and per-file bridge outcome.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from agent import lean_bridge
from agent.config import AgentConfig
from agent.lean_bridge_helpers import (
    count_lean_verified_unknowns,
    extract_unknown_atoms,
    merge_lean_cert_into_proof_cert,
)


def demote_atoms_to_unknown(
    cert: dict, atom_names: set[str]
) -> tuple[dict, list[str]]:
    """Return a copy of *cert* with the named atoms demoted to Z3 ``unknown``.

    B-4 demonstrator hook: a benchmark atom Z3 actually proved (``unsat``)
    can be exercised through the external-proof route as if the solver had
    been inconclusive — e.g. the 群 3 while-loop atoms whose verification
    conditions are the intended AI-proof inputs.  Only the bridge reads the
    demoted copy (it is written to ``<stem>.forced.proof-cert.json``); the
    merged output certificate then carries the atom's ``lean_verified``
    upgrade like any proven escalation, and ``forced_atoms`` in the run
    manifest records which atoms were demoted for the run.
    """
    bridge_cert = copy.deepcopy(cert)
    forced: list[str] = []
    for atom in bridge_cert.get("atoms", []):
        if isinstance(atom, dict) and atom.get("name") in atom_names:
            atom["status"] = "unknown"
            atom["z3_check_result"] = "unknown"
            atom["z3_result_class"] = "unknown"
            forced.append(str(atom["name"]))
    if forced:
        bridge_cert["all_verified"] = False
    return bridge_cert, forced


def _count_verified(cert: dict, names: set[str]) -> int:
    return sum(
        1
        for atom in cert.get("atoms", [])
        if isinstance(atom, dict)
        and atom.get("name") in names
        and atom.get("z3_check_result") == "lean_verified"
    )


def _restore_forced_misses(
    original: dict, upgraded: dict, names: set[str]
) -> dict:
    """Forced atoms whose Lean attempt failed revert to the Z3 verdict.

    A forced atom is ``unknown`` only in the bridge input; when the
    external-proof route does not verify it, the output certificate must
    keep Z3's original verdict instead of reporting a regression."""
    original_by_name = {
        a.get("name"): a
        for a in original.get("atoms", [])
        if isinstance(a, dict)
    }
    for atom in upgraded.get("atoms", []):
        if not isinstance(atom, dict) or atom.get("name") not in names:
            continue
        if atom.get("z3_check_result") == "lean_verified":
            continue
        source = original_by_name.get(atom.get("name"))
        if not isinstance(source, dict):
            continue
        for field in ("z3_check_result", "z3_result_class", "status"):
            if field in source:
                atom[field] = source[field]
    return upgraded


def _z3_proof_cert(
    mumei_bin: str, source: Path, out: Path, timeout: float
) -> tuple[dict | None, dict[str, object]]:
    """Run ``mumei verify --proof-cert`` and return ``(certificate, diagnostics)``.

    Any file already at ``out`` is removed first so a stale certificate from a
    previous run can never be attributed to this invocation. ``diagnostics``
    records the exit code and the tail of stdout/stderr so a missing
    certificate can be told apart from a malformed one or a verifier crash.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    cmd = [*mumei_bin.split(), "verify", "--proof-cert", "--output", str(out), str(source)]
    diagnostics: dict[str, object] = {"returncode": None, "output_tail": ""}
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        diagnostics["error"] = f"timeout after {timeout}s: {exc}"
        return None, diagnostics
    diagnostics["returncode"] = proc.returncode
    diagnostics["output_tail"] = (proc.stdout + proc.stderr)[-2000:]
    if not out.is_file():
        diagnostics["error"] = "no_proof_certificate"
        return None, diagnostics
    try:
        cert = json.loads(out.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        diagnostics["error"] = f"malformed_proof_certificate: {exc}"
        return None, diagnostics
    if not isinstance(cert, dict):
        diagnostics["error"] = "malformed_proof_certificate: not an object"
        return None, diagnostics
    return cert, diagnostics


def _generator(config: AgentConfig, mode: str):
    if mode != "on":
        return None
    if not config.lean_ai_proof_active():
        raise SystemExit(
            "--ai-proof on requires ENABLE_LEAN_AI_PROOF=1, an LLM_API_KEY and "
            "CI_FIXTURE_MODE unset"
        )
    from agent.lean_ai_proof import LLMAiProofGenerator

    return LLMAiProofGenerator(config)


def measure_one(
    source: Path,
    *,
    benchmarks_dir: Path,
    work_dir: Path,
    cert_dir: Path,
    config: AgentConfig,
    generator,
    timeout: float,
    force_atoms: frozenset[str] = frozenset(),
) -> dict[str, object]:
    rel = source.relative_to(benchmarks_dir)
    z3_cert_path = work_dir / rel.parent / f"{rel.stem}.z3.proof-cert.json"
    out = cert_dir / rel.parent / f"{rel.stem}.proof.json"
    out.unlink(missing_ok=True)
    started = time.monotonic()
    cert, verify_diag = _z3_proof_cert(config.mumei_bin, source, z3_cert_path, timeout)
    entry: dict[str, object] = {
        "file": str(rel).replace(os.sep, "/"),
        "certificate": None,
        "verify_returncode": verify_diag["returncode"],
        "unknown_atoms": 0,
        "lean_verified_unknowns": 0,
        "forced_atoms": [],
        "lean_verified_forced": 0,
        "bridge": None,
    }
    if cert is None:
        entry["error"] = verify_diag.get("error", "no_proof_certificate")
        entry["verify_output_tail"] = verify_diag["output_tail"]
        entry["elapsed_s"] = round(time.monotonic() - started, 3)
        return entry
    unknown = extract_unknown_atoms(cert)
    entry["unknown_atoms"] = len(unknown)
    bridge_cert_path = z3_cert_path
    bridge_cert = cert
    forced_names: list[str] = []
    if force_atoms:
        bridge_cert, forced_names = demote_atoms_to_unknown(cert, force_atoms)
        if forced_names:
            forced_path = (
                work_dir / rel.parent / f"{rel.stem}.forced.proof-cert.json"
            )
            forced_path.write_text(
                json.dumps(bridge_cert, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            bridge_cert_path = forced_path
    entry["forced_atoms"] = forced_names
    # The merge reads the bridge input: a forced atom is ``unknown`` there,
    # so its lean_verified record upgrades like any proven escalation.
    upgraded = bridge_cert
    if unknown or forced_names:
        lean_cert_out = work_dir / rel.parent / f"{rel.stem}.lean-cert.json"
        evidence_dir = (
            Path(config.lean_ai_proof_evidence_dir) / rel.parent / rel.stem
            if config.lean_ai_proof_evidence_dir
            else None
        )
        bridge_result = lean_bridge.run_lean_bridge(
            cert_path=bridge_cert_path,
            lean_cert_out=lean_cert_out,
            mumei_lean_repo=config.mumei_lean_repo or "",
            timeout=timeout,
            ai_proof_generator=generator,
            ai_proof_max_attempts=config.lean_ai_proof_max_attempts,
            ai_proof_evidence_dir=evidence_dir,
        )
        lean_cert = bridge_result.get("lean_cert")
        if isinstance(lean_cert, dict):
            upgraded = merge_lean_cert_into_proof_cert(bridge_cert, lean_cert)
            entry["lean_verified_unknowns"] = count_lean_verified_unknowns(
                cert, upgraded
            )
            entry["lean_verified_forced"] = _count_verified(
                upgraded, set(forced_names)
            )
        entry["bridge"] = {
            key: bridge_result.get(key)
            for key in (
                "success",
                "returncode",
                "error_code",
                "fallback_strategy",
                "duration_seconds",
                "ai_proof_used",
                "ai_proof_proved",
                "ai_proof_attempted",
                "ai_proof_residual",
            )
        }
    if forced_names:
        # Whether the bridge produced a lean_cert or failed outright, a
        # forced atom that did not reach lean_verified keeps its Z3 verdict.
        upgraded = _restore_forced_misses(cert, upgraded, set(forced_names))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(upgraded, indent=2, ensure_ascii=False), encoding="utf-8")
    entry["certificate"] = str(out)
    entry["elapsed_s"] = round(time.monotonic() - started, 3)
    return entry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--benchmarks-dir", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--cert-dir", type=Path, required=True)
    parser.add_argument("--ai-proof", choices=("on", "off"), default="on")
    parser.add_argument("--timeout", type=float, default=1800.0)
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="Restrict to <category>/<file>.mm entries (repeatable)",
    )
    parser.add_argument(
        "--candidates-only",
        action="store_true",
        help="Only write certificates for files that had Z3 unknown atoms",
    )
    parser.add_argument(
        "--force-lean-atom",
        action="append",
        default=[],
        metavar="ATOM",
        help="B-4 demonstrator: demote the named atom to Z3 'unknown' for the "
        "bridge input (repeatable), so an atom Z3 already proved still "
        "reaches the external-proof route (e.g. the 群3 while-loop VCs). "
        "Recorded under forced_atoms in run.json.",
    )
    args = parser.parse_args()

    config = AgentConfig()
    if not lean_bridge.lean_fallback_available(config.mumei_lean_repo):
        raise SystemExit("MUMEI_LEAN_REPO must point at a mumei-lean checkout")
    generator = _generator(config, args.ai_proof)

    files = sorted(
        p for p in args.benchmarks_dir.rglob("*.mm") if p.parent != args.benchmarks_dir
    )
    if args.only:
        wanted = set(args.only)
        files = [f for f in files if str(f.relative_to(args.benchmarks_dir)) in wanted]
    args.work_dir.mkdir(parents=True, exist_ok=True)
    args.cert_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {
        "schema": "mumei-agent.lean_ai_proof_run/v1",
        "ai_proof": args.ai_proof,
        "llm_model": config.model if args.ai_proof == "on" else None,
        "llm_base_url": config.base_url if args.ai_proof == "on" else None,
        "lean_ai_proof_max_attempts": config.lean_ai_proof_max_attempts,
        "mumei_bin": config.mumei_bin,
        "mumei_lean_repo": config.mumei_lean_repo,
        "files": [],
    }
    force_atoms = frozenset(args.force_lean_atom)
    manifest["force_lean_atoms"] = sorted(force_atoms)
    entries: list[dict[str, object]] = []
    for source in files:
        rel = str(source.relative_to(args.benchmarks_dir)).replace(os.sep, "/")
        print(f"[lean-ai-proof:{args.ai_proof}] {rel}", flush=True)
        entry = measure_one(
            source,
            benchmarks_dir=args.benchmarks_dir,
            work_dir=args.work_dir,
            cert_dir=args.cert_dir,
            config=config,
            generator=generator,
            timeout=args.timeout,
            force_atoms=force_atoms,
        )
        if (
            args.candidates_only
            and not entry["unknown_atoms"]
            and not entry["forced_atoms"]
        ):
            cert_path = entry.get("certificate")
            if isinstance(cert_path, str):
                Path(cert_path).unlink(missing_ok=True)
            entry["certificate"] = None
        entries.append(entry)
        manifest["files"] = entries
        (args.cert_dir / "run.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(
            f"  -> unknown={entry['unknown_atoms']} "
            f"forced={len(entry['forced_atoms'])} "
            f"lean_verified={entry['lean_verified_unknowns']}"
            f"+{entry['lean_verified_forced']} "
            f"elapsed={entry.get('elapsed_s')}s",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
