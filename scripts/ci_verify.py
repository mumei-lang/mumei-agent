#!/usr/bin/env python3
"""CI Verification Gate: run mumei verify on all .mm files and format results.

Usage:
    python scripts/ci_verify.py [--mumei-bin MUMEI_BIN] [--proof-cert] [FILES...]

If no files are specified, discovers all .mm files in the repository.
Outputs GitHub-flavored Markdown summary to stdout.
Exit code: 0 if all pass, 1 if any fail.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone


def discover_mm_files(root: Path) -> list[Path]:
    """Find all .mm files in the repository, excluding hidden dirs and node_modules."""
    mm_files = []
    for p in sorted(root.rglob("*.mm")):
        # Skip hidden directories, node_modules, etc.
        parts = p.relative_to(root).parts
        if any(part.startswith(".") or part == "node_modules" for part in parts):
            continue
        mm_files.append(p)
    return mm_files


def run_verify(mumei_bin: str, file_path: Path) -> dict:
    """Run mumei verify --json on a single file."""
    cmd = mumei_bin.split() + ["verify", "--json", str(file_path)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        return {
            "file": str(file_path),
            "success": False,
            "report": {},
            "stdout": "",
            "stderr": f"mumei binary not found: {mumei_bin}",
        }
    except subprocess.TimeoutExpired:
        return {
            "file": str(file_path),
            "success": False,
            "report": {},
            "stdout": "",
            "stderr": f"Verification timed out after 120s: {file_path}",
        }
    report = {}
    if result.stdout.strip():
        try:
            report = json.loads(result.stdout)
        except json.JSONDecodeError:
            pass
    return {
        "file": str(file_path),
        "success": result.returncode == 0,
        "report": report,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def run_proof_cert(mumei_bin: str, file_path: Path, output_dir: Path) -> Path | None:
    """Run mumei verify --proof-cert and return the certificate path."""
    try:
        rel = file_path.resolve().relative_to(Path.cwd().resolve())
        safe_name = str(rel).replace(os.sep, "_").replace("/", "_")
    except ValueError:
        safe_name = file_path.stem
    if safe_name.endswith(".mm"):
        safe_name = safe_name[:-3]
    cert_path = output_dir / f"{safe_name}.proof.json"
    cmd = mumei_bin.split() + [
        "verify", "--proof-cert", "--output", str(cert_path), str(file_path)
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode == 0 and cert_path.exists():
        return cert_path
    return None


def format_markdown_summary(results: list[dict], proof_certs: list[Path]) -> str:
    """Format verification results as GitHub-flavored Markdown."""
    lines = []
    lines.append("## Mumei Verification Report")
    lines.append("")

    total = len(results)
    passed = sum(1 for r in results if r["success"])
    failed = total - passed

    if failed == 0:
        lines.append(f"**All {total} file(s) verified successfully.**")
    else:
        lines.append(f"**{failed} of {total} file(s) failed verification.**")
    lines.append("")

    # Summary table
    lines.append("| File | Status | Details |")
    lines.append("|------|--------|---------|")
    for r in results:
        file_name = Path(r["file"]).name
        status = "Passed" if r["success"] else "Failed"
        icon = "white_check_mark" if r["success"] else "x"

        details = ""
        report = r.get("report", {})
        if not r["success"]:
            failure_type = report.get("failure_type", "")
            violation_type = report.get("violation_type", "")
            atom = report.get("atom", "")
            reason = report.get("reason", "")
            if atom:
                details = f"`{atom}`: "
            if violation_type:
                details += violation_type
            elif failure_type:
                details += failure_type
            elif reason:
                details += reason[:80]
        else:
            # Show verified/skipped counts if available
            verified = report.get("verified", "")
            skipped = report.get("skipped", "")
            if verified:
                details = f"{verified} verified"
                if skipped:
                    details += f", {skipped} cached"

        # Escape pipe characters to avoid breaking the Markdown table
        details = details.replace("|", "\\|")
        lines.append(f"| `{file_name}` | :{icon}: {status} | {details} |")

    # Failure details
    failures = [r for r in results if not r["success"]]
    if failures:
        lines.append("")
        lines.append("### Failure Details")
        lines.append("")
        for r in failures:
            file_name = Path(r["file"]).name
            report = r.get("report", {})
            lines.append(f"#### `{file_name}`")
            lines.append("")

            # Counterexample
            ce = report.get("counterexample", {})
            if ce:
                ce_str = ", ".join(f"{k}={v}" for k, v in ce.items())
                lines.append(f"**Counterexample**: `{ce_str}`")

            # Suggestion
            suggestion = report.get("suggestion", "")
            if suggestion:
                lines.append(f"**Suggestion**: {suggestion}")

            # Semantic feedback
            sf = report.get("semantic_feedback", {})
            violated = sf.get("violated_constraints", [])
            if violated:
                lines.append("")
                lines.append("**Violated constraints**:")
                for vc in violated[:3]:  # Limit to 3
                    param = vc.get("param", "")
                    constraint = vc.get("constraint", "")
                    lines.append(f"- `{param}`: `{constraint}`")

            # Stderr (truncated)
            if r.get("stderr"):
                stderr_lines = r["stderr"].strip().split("\n")
                truncated = "\n".join(stderr_lines[:10])
                lines.append("")
                lines.append("<details>")
                lines.append("<summary>Error output</summary>")
                lines.append("")
                lines.append(f"```\n{truncated}\n```")
                lines.append("</details>")
            lines.append("")

    # Proof certificates
    if proof_certs:
        lines.append("")
        lines.append("### Proof Certificates")
        lines.append("")
        lines.append(f"{len(proof_certs)} proof certificate(s) generated and uploaded as artifacts.")

    # Footer
    lines.append("")
    lines.append("---")
    lines.append(f"*Generated by mumei-agent CI Verification Gate at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}*")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="CI Verification Gate for Mumei")
    parser.add_argument("files", nargs="*", help="Specific .mm files to verify")
    parser.add_argument("--mumei-bin", default="mumei", help="Path to mumei binary")
    parser.add_argument("--proof-cert", action="store_true", help="Generate proof certificates")
    parser.add_argument("--cert-dir", default="proof-certs", help="Directory for proof certificates")
    parser.add_argument("--output", default=None, help="Write markdown to file instead of stdout")
    args = parser.parse_args()

    root = Path.cwd()

    if args.files:
        mm_files = [Path(f) for f in args.files]
    else:
        mm_files = discover_mm_files(root)

    if not mm_files:
        print("No .mm files found.", file=sys.stderr)
        sys.exit(0)

    print(f"Verifying {len(mm_files)} file(s)...", file=sys.stderr)

    results = []
    for f in mm_files:
        print(f"  Verifying {f}...", file=sys.stderr)
        result = run_verify(args.mumei_bin, f)
        results.append(result)

    proof_certs = []
    if args.proof_cert:
        cert_dir = Path(args.cert_dir)
        cert_dir.mkdir(parents=True, exist_ok=True)
        for f in mm_files:
            cert = run_proof_cert(args.mumei_bin, f, cert_dir)
            if cert:
                proof_certs.append(cert)

    markdown = format_markdown_summary(results, proof_certs)

    if args.output:
        Path(args.output).write_text(markdown, encoding="utf-8")
    else:
        print(markdown)

    # Write structured JSON for programmatic consumption
    json_output = {
        "total": len(results),
        "passed": sum(1 for r in results if r["success"]),
        "failed": sum(1 for r in results if not r["success"]),
        "results": results,
        "proof_certificates": [str(p) for p in proof_certs],
    }

    json_path = Path(args.output).with_suffix(".json") if args.output else None
    if json_path:
        json_path.write_text(json.dumps(json_output, indent=2, ensure_ascii=False), encoding="utf-8")

    # Set GitHub Actions output if running in CI
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"passed={json_output['passed']}\n")
            f.write(f"failed={json_output['failed']}\n")
            f.write(f"total={json_output['total']}\n")

    sys.exit(0 if json_output["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
