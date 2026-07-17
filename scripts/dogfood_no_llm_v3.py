#!/usr/bin/env python3
"""Run validate-code --no-llm --no-mumei over all source files in oss-dogfood and report failures."""

from __future__ import annotations

import json
import subprocess
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

REPO = Path("/home/ubuntu/repos/mumei-agent")
OSS = Path("/home/ubuntu/repos/oss-dogfood")
OUT_DIR = Path("/tmp/dogfood_no_llm_v3")
OUT_DIR.mkdir(exist_ok=True)

EXT_TO_LANG = {
    ".py": "python",
    ".go": "go",
    ".rs": "rust",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".sol": "solidity",
}


def _run(path: Path) -> dict:
    rel = str(path.relative_to(OSS))
    lang = EXT_TO_LANG.get(path.suffix, "typescript")
    out = OUT_DIR / f"{rel.replace('/', '_').replace('.', '_')}.json"
    cmd = [
        str(REPO / ".venv/bin/python"),
        "-m",
        "agent",
        "validate-code",
        "--no-llm",
        "--no-mumei",
        "--input",
        str(path),
        "--language",
        lang,
        "--output",
        str(out),
    ]
    res: dict = {
        "file": rel,
        "lang": lang,
        "status": "ok",
    }
    try:
        proc = subprocess.run(
            cmd,
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=45,
        )
    except subprocess.TimeoutExpired:
        res["status"] = "timeout"
        return res
    except Exception as exc:
        res["status"] = "exception"
        res["exception"] = str(exc)
        return res

    res["exit_code"] = proc.returncode
    if out.exists():
        try:
            data = json.loads(out.read_text())
            res["verdict"] = data.get("verdict")
            res["atoms"] = len(data.get("inferred_atoms", []))
            res["warnings_count"] = len(data.get("warnings", []))
            res["errors"] = data.get("errors", [])
        except Exception as exc:
            res["status"] = "json_err"
            res["json_exception"] = str(exc)
    else:
        res["status"] = "no_output"
        res["stderr"] = proc.stderr[:500]
    return res


def main() -> None:
    files = [
        p
        for ext, lang in EXT_TO_LANG.items()
        for p in OSS.rglob(f"*{ext}")
        if ".git" not in str(p)
    ]
    summary = []
    with ProcessPoolExecutor(max_workers=4) as pool:
        for idx, res in enumerate(pool.map(_run, files)):
            summary.append(res)
            if (idx + 1) % 100 == 0:
                print(f"processed {idx + 1}/{len(files)}", flush=True)
                (OUT_DIR / "summary.json").write_text(
                    json.dumps(summary, indent=2, ensure_ascii=False)
                )
    (OUT_DIR / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False)
    )
    failures = [r for r in summary if r["status"] != "ok"]
    unverifiable = [r for r in summary if r.get("verdict") == "unverifiable"]
    print(f"DONE files={len(files)} failures={len(failures)} unverifiable={len(unverifiable)}")


if __name__ == "__main__":
    main()
