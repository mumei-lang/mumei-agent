#!/usr/bin/env python3
"""Run validate-code with local LLM on files that were unverifiable with --no-llm.

This script is meant to be run in the background; it writes a JSON summary and
stops at the first parse/JSON/extraction failure so a human can triage and fix.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

REPO = Path("/home/ubuntu/repos/mumei-agent")
OSS = Path("/home/ubuntu/repos/oss-dogfood")
NO_LLM_SUMMARY = Path("/tmp/dogfood_no_llm_all/summary.json")
OUT_DIR = Path("/tmp/dogfood_llm_unverifiable")
FAIL_DIR = Path("/tmp/mumei_json_failures")
ENV = os.environ.copy()
ENV["LLM_MODEL"] = "qwen2.5-coder:1.5b"
ENV["LLM_MAX_TOKENS"] = "512"

EXT_LANG = {
    ".py": "python",
    ".rs": "rust",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".sol": "solidity",
}


def _stop_ollama() -> None:
    try:
        subprocess.run(
            ["docker", "exec", "mumei-ollama", "ollama", "stop", ENV["LLM_MODEL"]],
            capture_output=True,
            timeout=10,
        )
    except Exception:
        pass
    # wait until idle
    for _ in range(30):
        try:
            r = subprocess.run(
                ["docker", "exec", "mumei-ollama", "ollama", "ps"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if ENV["LLM_MODEL"] not in r.stdout:
                return
        except Exception:
            return
        time.sleep(1)


def _run_one(path: Path, lang: str, out: Path) -> dict:
    cmd = [
        str(REPO / ".venv/bin/python"),
        "-m",
        "agent",
        "validate-code",
        "--no-mumei",
        "--input",
        str(path),
        "--language",
        lang,
        "--output",
        str(out),
    ]
    result: dict = {"path": str(path.relative_to(OSS)), "status": "ok"}
    try:
        proc = subprocess.run(
            cmd,
            cwd=REPO,
            env=ENV,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except subprocess.TimeoutExpired:
        result["status"] = "timeout"
        _stop_ollama()
        return result
    except Exception as exc:
        result["status"] = "exception"
        result["exception"] = str(exc)
        return result

    result["exit_code"] = proc.returncode
    if out.exists():
        try:
            data = json.loads(out.read_text())
            result["verdict"] = data.get("verdict")
            result["atoms"] = len(data.get("inferred_atoms", []))
            result["warnings"] = len(data.get("warnings", []))
            result["errors"] = data.get("errors", [])
        except Exception as exc:
            result["status"] = "json_err"
            result["json_exception"] = str(exc)
    else:
        result["status"] = "no_output"

    if result["exit_code"] not in (0, 2) or result.get("errors"):
        result["status"] = "failure"
    return result


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    FAIL_DIR.mkdir(exist_ok=True)
    summary: list[dict] = []
    no_llm = json.loads(NO_LLM_SUMMARY.read_text())
    unverifiable = [
        r
        for r in no_llm
        if r.get("verdict") == "unverifiable" and Path(OSS / r["file"]).exists()
    ]
    print(f"processing {len(unverifiable)} unverifiable files with local LLM")
    for idx, r in enumerate(unverifiable, 1):
        path = OSS / r["file"]
        lang = EXT_LANG.get(path.suffix)
        if not lang:
            continue
        out = OUT_DIR / f"{path.relative_to(OSS).as_posix().replace('/', '_').replace('.', '_')}.json"
        res = _run_one(path, lang, out)
        summary.append(res)
        print(f"[{idx}/{len(unverifiable)}] {res['path']} -> {res['status']}")
        if res["status"] in ("failure", "json_err", "exception"):
            (OUT_DIR / "summary.json").write_text(
                json.dumps(summary, indent=2, ensure_ascii=False)
            )
            print("STOPPED on failure; see summary.json")
            return
        if idx % 10 == 0:
            (OUT_DIR / "summary.json").write_text(
                json.dumps(summary, indent=2, ensure_ascii=False)
            )
    (OUT_DIR / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False)
    )
    print("DONE")


if __name__ == "__main__":
    main()
