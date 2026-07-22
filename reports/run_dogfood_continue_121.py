#!/usr/bin/env python3
"""Run no-LLM dogfooding audit for batch 113."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPORT_DIR = Path(__file__).parent / "dogfood_continue_121"
SAMPLE_FILE = Path(__file__).parent / "dogfood_continue_121_sample.json"


def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    sample = json.loads(SAMPLE_FILE.read_text())
    summary: list[dict] = []
    for item in sample:
        repo = item["repo"]
        lang = item["lang"]
        file = item["file"]
        print(f"[no-llm] {file}")
        result = subprocess.run(
            [
                "uv",
                "run",
                "python",
                "-m",
                "agent",
                "audit",
                "--code-file",
                file,
                "--language",
                lang,
                "--format",
                "json",
            ],
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            env={**__import__("os").environ, "LLM_API_KEY": ""},
        )
        errors: list[str] = []
        status = "verified"
        try:
            data = json.loads(result.stdout)
            status = data.get("verification_status", status)
            violations = data.get("verification_violations", [])
            if violations:
                errors = [v["message"] if isinstance(v, dict) else str(v) for v in violations]
        except Exception as exc:
            status = "unverifiable"
            errors = [str(exc), result.stderr[:500]]
        out = {
            "repo": repo,
            "file": file,
            "language": lang,
            "status": status,
            "errors": errors,
        }
        summary.append(out)
        out_file = REPORT_DIR / (
            file.replace("/", "__").replace("\\", "__") + ".json"
        )
        out_file.write_text(json.dumps(out, ensure_ascii=False, indent=2))
        print(f"  -> {status} (errors={len(errors)})")
    (REPORT_DIR / "_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2)
    )
    verified = sum(1 for s in summary if s["status"] == "verified")
    print(f"\nBatch 121: {verified}/{len(summary)} verified")


if __name__ == "__main__":
    main()
