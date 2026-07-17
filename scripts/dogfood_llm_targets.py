#!/usr/bin/env python3
"""Run validate-code with local LLM on files that were unverifiable with --no-llm."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

REPO = Path("/home/ubuntu/repos/mumei-agent")
OSS = Path("/home/ubuntu/repos/oss-dogfood")
OUT_DIR = Path("/tmp/dogfood_llm_targets")
FAIL_DIR = Path("/tmp/mumei_json_failures")
ENV = os.environ.copy()
ENV["LLM_MODEL"] = "qwen2.5-coder:1.5b"
ENV["LLM_MAX_TOKENS"] = "2048"
ENV["MUMEI_DEBUG_JSON_FAIL_DIR"] = str(FAIL_DIR)

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
            timeout=15,
        )
    except Exception:
        pass
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
    res: dict = {"path": str(path.relative_to(OSS)), "status": "ok"}
    try:
        proc = subprocess.run(
            cmd,
            cwd=REPO,
            env=ENV,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        res["status"] = "timeout"
        _stop_ollama()
        return res
    except Exception as exc:
        res["status"] = "exception"
        res["exception"] = str(exc)
        return res

    res["exit_code"] = proc.returncode
    if out.exists():
        try:
            data = json.loads(out.read_text())
            warnings = data.get("warnings", [])
            res["verdict"] = data.get("verdict")
            res["atoms"] = len(data.get("inferred_atoms", []))
            res["warnings_count"] = len(warnings)
            res["errors"] = data.get("errors", [])
            if any("JSON" in str(w) or "LLM contract inference" in str(w) for w in warnings):
                res["status"] = "llm_json_warning"
        except Exception as exc:
            res["status"] = "json_err"
            res["json_exception"] = str(exc)
    else:
        res["status"] = "no_output"
    return res


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    FAIL_DIR.mkdir(exist_ok=True)
    targets = json.loads(open("/tmp/dogfood_unverifiable_target.json").read())
    # also include files with functions from combined summary
    summary = []
    for t in targets:
        path = OSS / t["file"]
        lang = t["lang"]
        if not path.exists():
            continue
        out = OUT_DIR / f"{path.relative_to(OSS).as_posix().replace('/', '_').replace('.', '_')}.json"
        res = _run_one(path, lang, out)
        summary.append(res)
        print(f"[{len(summary)}/{len(targets)}] {res['path']} -> {res['status']}", flush=True)
        (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
