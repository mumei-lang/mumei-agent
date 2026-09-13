#!/usr/bin/env python3
"""R-7: produce repair certificates for the mumei evaluation suite.

For every counterexample benchmark (``// expected: FAIL``) under the mumei
``benchmarks/`` tree this script copies the source into ``--work-dir`` (keeping
the ``<category>/<file>.mm`` layout the suite keys on), runs the self-healing
loop on the copy, and asks ``heal --proof-cert-out`` to emit a proof
certificate whose ``self_correction_summary`` records the repair outcome.

The certificate directory is then consumed by::

    python3 benchmarks/evaluation_suite.py --repair-cert-dir <cert-dir> ...

in the mumei repository, which turns the repair-convergence axis from
``SKIP`` into ``MEASURED``. A ``run.json`` manifest (model, attempts,
per-file stop reasons) is written next to the certificates so the
measurement is reproducible.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from agent.config import AgentConfig

EXPECTED_FAIL_RE = re.compile(r"^\s*//\s*expected:\s*FAIL\b", re.MULTILINE)


def find_counterexample_files(benchmarks_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(benchmarks_dir.rglob("*.mm")):
        if path.parent == benchmarks_dir:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if EXPECTED_FAIL_RE.search(text):
            files.append(path)
    return files


def heal_one(
    source: Path,
    *,
    benchmarks_dir: Path,
    work_dir: Path,
    cert_dir: Path,
    max_retries: int,
    timeout: float,
) -> dict[str, object]:
    rel = source.relative_to(benchmarks_dir)
    copy = work_dir / rel
    copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, copy)
    cert_out = cert_dir / rel.parent / f"{rel.stem}.proof.json"
    cert_out.unlink(missing_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "agent",
        "heal",
        str(copy),
        "--max-retries",
        str(max_retries),
        "--proof-cert-out",
        str(cert_out),
    ]
    started = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
        returncode: int | None = proc.returncode
        tail = (proc.stdout + proc.stderr)[-2000:]
    except subprocess.TimeoutExpired as exc:
        returncode = None
        tail = f"timeout after {timeout}s: {exc}"
    elapsed = time.monotonic() - started
    summary: dict[str, object] | None = None
    if cert_out.is_file():
        try:
            cert = json.loads(cert_out.read_text(encoding="utf-8"))
            summary = cert.get("self_correction_summary")
        except (json.JSONDecodeError, OSError):
            summary = None
    return {
        "file": str(rel).replace(os.sep, "/"),
        "returncode": returncode,
        "elapsed_s": round(elapsed, 3),
        "certificate": str(cert_out) if cert_out.is_file() else None,
        "self_correction_summary": summary,
        "log_tail": tail,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--benchmarks-dir",
        type=Path,
        required=True,
        help="mumei benchmarks/ directory",
    )
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--cert-dir", type=Path, required=True)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=1800.0)
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="Restrict to <category>/<file>.mm entries (repeatable)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip files whose certificate already exists",
    )
    args = parser.parse_args()

    files = find_counterexample_files(args.benchmarks_dir)
    if args.only:
        wanted = set(args.only)
        files = [
            f for f in files if str(f.relative_to(args.benchmarks_dir)) in wanted
        ]
    args.work_dir.mkdir(parents=True, exist_ok=True)
    args.cert_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.cert_dir / "run.json"
    config = AgentConfig()
    manifest: dict[str, object] = {
        "schema": "mumei-agent.repair_convergence_run/v1",
        "llm_model": config.model,
        "llm_base_url": config.base_url,
        "mumei_bin": config.mumei_bin,
        "max_retries": args.max_retries,
        "files": [],
    }
    if args.resume and manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["llm_model"] = config.model
            manifest["llm_base_url"] = config.base_url
            manifest["mumei_bin"] = config.mumei_bin
        except (json.JSONDecodeError, OSError):
            pass
    done = {
        entry["file"]
        for entry in manifest.get("files", [])  # type: ignore[union-attr]
        if isinstance(entry, dict) and entry.get("certificate")
    }
    for source in files:
        rel = str(source.relative_to(args.benchmarks_dir)).replace(os.sep, "/")
        if args.resume and rel in done:
            continue
        print(f"[heal] {rel}", flush=True)
        entry = heal_one(
            source,
            benchmarks_dir=args.benchmarks_dir,
            work_dir=args.work_dir,
            cert_dir=args.cert_dir,
            max_retries=args.max_retries,
            timeout=args.timeout,
        )
        manifest["files"] = [  # type: ignore[assignment]
            e for e in manifest.get("files", []) if e.get("file") != rel  # type: ignore[union-attr]
        ] + [entry]
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(
            f"  -> summary={json.dumps(entry['self_correction_summary'])} "
            f"elapsed={entry['elapsed_s']}s",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
