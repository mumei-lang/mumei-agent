#!/usr/bin/env python3
"""Fast in-process no-LLM / no-Mumei sweep over oss-dogfood source files."""

from __future__ import annotations

import json
import os
import traceback
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

REPO = Path("/home/ubuntu/repos/mumei-agent")
OSS = Path("/home/ubuntu/repos/oss-dogfood")
OUT_DIR = Path("/tmp/dogfood_no_llm_v3_fast")
OUT_DIR.mkdir(exist_ok=True)

EXT_TO_LANG = {
    ".py": "python",
    ".go": "go",
    ".rs": "rust",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".sol": "solidity",
}


def _init_worker() -> None:
    import sys

    sys.path.insert(0, str(REPO))
    # Load .env into this worker's environment so AgentConfig sees it.
    env_file = REPO / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def _run(path: Path) -> dict:
    rel = str(path.relative_to(OSS))
    lang = EXT_TO_LANG.get(path.suffix, "typescript")
    out = OUT_DIR / f"{rel.replace('/', '_').replace('.', '_')}.json"
    res: dict = {
        "file": rel,
        "lang": lang,
        "status": "ok",
    }
    try:
        from agent.config import AgentConfig
        from agent.cross_validation import validate_foreign_code

        config = AgentConfig()
        result = validate_foreign_code(
            path.read_text(encoding="utf-8", errors="ignore"),
            lang,
            config=config,
            use_llm=False,
            run_mumei=False,
        )
        data = asdict(result)
        res["verdict"] = data.get("verdict")
        res["success"] = data.get("success")
        res["atoms"] = len(data.get("inferred_atoms", []))
        res["warnings_count"] = len(data.get("warnings", []))
        res["errors"] = data.get("errors", [])
        res["warnings_sample"] = data.get("warnings", [])[:5]
        out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        res["status"] = "exception"
        res["exception"] = traceback.format_exc()
    return res


def main() -> None:
    files = [
        p
        for ext in EXT_TO_LANG
        for p in OSS.rglob(f"*{ext}")
        if ".git" not in str(p)
    ]
    summary = []
    with ProcessPoolExecutor(max_workers=8, initializer=_init_worker) as pool:
        for idx, res in enumerate(pool.map(_run, files)):
            summary.append(res)
            if (idx + 1) % 100 == 0:
                print(f"processed {idx + 1}/{len(files)}", flush=True)
                (OUT_DIR / "summary.json").write_text(
                    json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
                )
    (OUT_DIR / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    exceptions = [r for r in summary if r["status"] != "ok"]
    unverifiable = [r for r in summary if r.get("verdict") == "unverifiable"]
    refuted = [r for r in summary if r.get("verdict") == "refuted"]
    print(
        f"DONE files={len(files)} exceptions={len(exceptions)} "
        f"unverifiable={len(unverifiable)} refuted={len(refuted)}"
    )


if __name__ == "__main__":
    main()
