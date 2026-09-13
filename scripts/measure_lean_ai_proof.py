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


def _z3_proof_cert(mumei_bin: str, source: Path, out: Path, timeout: float) -> dict | None:
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [*mumei_bin.split(), "verify", "--proof-cert", "--output", str(out), str(source)]
    subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    if not out.is_file():
        return None
    try:
        cert = json.loads(out.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return cert if isinstance(cert, dict) else None


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
) -> dict[str, object]:
    rel = source.relative_to(benchmarks_dir)
    z3_cert_path = work_dir / rel.parent / f"{rel.stem}.z3.proof-cert.json"
    out = cert_dir / rel.parent / f"{rel.stem}.proof.json"
    started = time.monotonic()
    cert = _z3_proof_cert(config.mumei_bin, source, z3_cert_path, timeout)
    entry: dict[str, object] = {
        "file": str(rel).replace(os.sep, "/"),
        "certificate": None,
        "unknown_atoms": 0,
        "lean_verified_unknowns": 0,
        "bridge": None,
    }
    if cert is None:
        entry["error"] = "no_proof_certificate"
        entry["elapsed_s"] = round(time.monotonic() - started, 3)
        return entry
    unknown = extract_unknown_atoms(cert)
    entry["unknown_atoms"] = len(unknown)
    upgraded = cert
    if unknown:
        lean_cert_out = work_dir / rel.parent / f"{rel.stem}.lean-cert.json"
        evidence_dir = (
            Path(config.lean_ai_proof_evidence_dir) / rel.parent / rel.stem
            if config.lean_ai_proof_evidence_dir
            else None
        )
        bridge_result = lean_bridge.run_lean_bridge(
            cert_path=z3_cert_path,
            lean_cert_out=lean_cert_out,
            mumei_lean_repo=config.mumei_lean_repo or "",
            timeout=timeout,
            ai_proof_generator=generator,
            ai_proof_max_attempts=config.lean_ai_proof_max_attempts,
            ai_proof_evidence_dir=evidence_dir,
        )
        lean_cert = bridge_result.get("lean_cert")
        if isinstance(lean_cert, dict):
            upgraded = merge_lean_cert_into_proof_cert(cert, lean_cert)
            entry["lean_verified_unknowns"] = count_lean_verified_unknowns(cert, upgraded)
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
        )
        if args.candidates_only and not entry["unknown_atoms"]:
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
            f"lean_verified={entry['lean_verified_unknowns']} "
            f"elapsed={entry.get('elapsed_s')}s",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
