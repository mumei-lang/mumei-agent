#!/usr/bin/env python3
"""Zero-Human Challenge Runner.

Run mumei-agent's generate pipeline against challenge specifications
and record full logs of each attempt.

Usage:
    python -m examples.challenges.run_challenge <spec_path> [--log-dir DIR] [--dry-run]
    python -m examples.challenges.run_challenge --all [--log-dir DIR] [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime
import json
import shutil
import sys
import time
from pathlib import Path


# ---------------------------------------------------------------------------
# Spec discovery
# ---------------------------------------------------------------------------

CHALLENGES_DIR = Path(__file__).parent
DEFAULT_RESULTS_DIR = CHALLENGES_DIR / "results"


def discover_specs() -> list[Path]:
    """Return all ``*_spec.json`` files in the challenges directory."""
    return sorted(CHALLENGES_DIR.glob("*_spec.json"))


# ---------------------------------------------------------------------------
# Validation (reuses the same pattern as run_e2e_demo.py)
# ---------------------------------------------------------------------------


def validate_spec(spec: dict) -> list[str]:
    """Validate a spec dict and return a list of error messages (empty = valid).

    Supports both single-atom specs (top-level name/params) and multi-atom
    specs (``atoms`` array with ``module_name``).
    """
    errors: list[str] = []

    # Multi-atom spec
    if "atoms" in spec:
        if not spec.get("module_name"):
            errors.append("multi-atom spec must have a non-empty 'module_name' field")
        atoms = spec["atoms"]
        if not isinstance(atoms, list) or len(atoms) == 0:
            errors.append("'atoms' must be a non-empty list")
        else:
            for i, atom in enumerate(atoms):
                if not isinstance(atom, dict) or not atom.get("name"):
                    errors.append(f"atoms[{i}] must be a dict with a 'name' field")
                params = atom.get("params", atom.get("inputs", []))
                if not isinstance(params, list):
                    errors.append(f"atoms[{i}].params must be a list")
        return errors

    # Single-atom spec
    if not spec.get("name"):
        errors.append("spec must have a non-empty 'name' field")
    params = spec.get("params", spec.get("inputs", []))
    if not isinstance(params, list):
        errors.append("'params' must be a list")
    else:
        for i, p in enumerate(params):
            if not isinstance(p, dict) or "name" not in p:
                errors.append(f"params[{i}] must be a dict with at least a 'name' key")
    return errors


def _mumei_available(mumei_bin: str = "mumei") -> bool:
    """Check whether the mumei binary is available."""
    first_token = mumei_bin.split()[0] if mumei_bin else "mumei"
    return shutil.which(first_token) is not None


# ---------------------------------------------------------------------------
# Single challenge runner
# ---------------------------------------------------------------------------


def run_challenge(spec_path: str, dry_run: bool = False) -> dict:
    """Run a single challenge through the generate pipeline.

    Args:
        spec_path: Path to the challenge spec JSON.
        dry_run: If True, validate spec only without LLM or mumei invocation.

    Returns:
        A result dict with keys: spec, code, verified, dry_run, errors, steps, log.
    """
    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)

    challenge_name = spec.get("module_name", spec.get("name", "unnamed"))

    result: dict = {
        "spec": spec,
        "spec_path": spec_path,
        "challenge_name": challenge_name,
        "code": "",
        "verified": False,
        "dry_run": dry_run,
        "errors": [],
        "steps": {},
        "log": {},
    }

    print(f"=== Zero-Human Challenge: {challenge_name} ===")
    print(f"Spec: {spec_path}")
    if "atoms" in spec:
        atom_names = [a.get("name", "<unnamed>") for a in spec["atoms"]]
        print(f"Atoms: {', '.join(atom_names)}")
    print()

    # Step 1: Validate spec
    validation_errors = validate_spec(spec)
    if validation_errors:
        for err in validation_errors:
            print(f"  VALIDATION ERROR: {err}")
        result["errors"] = validation_errors
        result["steps"]["spec_validation"] = False
        return result

    print("  [1/4] Spec validation: OK")
    result["steps"]["spec_validation"] = True

    if dry_run:
        print()
        print("=" * 60)
        print("RESULT: DRY RUN (spec validated, no generation/verification)")
        print("=" * 60)
        return result

    # Deferred imports (avoid import errors in dry-run mode)
    from agent.config import AgentConfig
    from agent.metrics import Metrics
    from agent.mumei_client import MumeiClient
    from agent.strategies.generate_strategy import generate_code

    # Step 2: Load config and clients
    config = AgentConfig()
    client = config.create_client()
    model = config.model

    mumei_client: MumeiClient | None = None
    if config.mumei_bin and _mumei_available(config.mumei_bin):
        mumei_client = MumeiClient(config.mumei_bin)
        print(f"  Using mumei binary: {config.mumei_bin}")
    else:
        print("  No mumei binary available — running in generation-only mode")
    print()

    # Step 3: Generate code
    print("  [2/4] Code generation ...")
    metrics = Metrics()
    start_time = time.time()
    code, verified = generate_code(
        client=client,
        model=model,
        spec=spec,
        config_max_retries=5,
        mumei_client=mumei_client,
        metrics=metrics,
    )
    elapsed = time.time() - start_time
    metrics.elapsed_seconds = round(elapsed, 2)
    metrics.challenge_name = challenge_name

    result["code"] = code
    result["verified"] = verified
    result["steps"]["generate"] = bool(code)
    result["steps"]["verify"] = verified
    result["log"] = {
        "challenge_name": challenge_name,
        "spec": spec,
        "generated_code": code,
        "verified": verified,
        "elapsed_seconds": round(elapsed, 2),
        "metrics": metrics.to_dict(),
    }

    # Step 4: Summary
    if code:
        print(f"  [3/4] Code generation: OK ({len(code)} chars)")
    else:
        print("  [3/4] Code generation: FAIL (empty output)")

    if verified:
        print("  [4/4] Verification: PASSED")
        # Record successful generation pattern for future reuse.
        # Use the spec JSON as source_before so that format_few_shot()
        # shows meaningful context and each challenge gets a unique
        # content_hash for deduplication.
        try:
            from agent.pattern_library import PatternLibrary
            pattern_lib = PatternLibrary()
            spec_text = json.dumps(spec, indent=2, ensure_ascii=False)
            pattern_lib.record(
                violation_type="generation",
                failure_type="generation",
                source_before=spec_text,
                source_after=code,
                report={"atom": challenge_name, "spec": spec},
                fix_method="llm",
            )
            print("  Pattern recorded for future reuse.")
        except Exception as exc:
            print(f"  (Pattern recording skipped: {exc})")
    else:
        print("  [4/4] Verification: FAILED")

    print()
    print("=" * 60)
    print("Pipeline Summary")
    print("=" * 60)
    step_labels = [
        ("spec_validation", "Spec Validation"),
        ("generate", "Code Generation"),
        ("verify", "Verification"),
    ]
    for key, label in step_labels:
        status_flag = result["steps"].get(key)
        if status_flag is None:
            mark = "SKIP"
        elif status_flag:
            mark = "OK"
        else:
            mark = "FAIL"
        print(f"  {label:<25s} {mark}")
    print("=" * 60)
    print(f"  Elapsed: {elapsed:.1f}s")
    print(f"  Metrics: {metrics.to_json()}")
    print()
    print("Generated code:")
    print("-" * 40)
    print(code)
    print("-" * 40)

    return result


# ---------------------------------------------------------------------------
# Results writer
# ---------------------------------------------------------------------------


def _write_results(result: dict, log_dir: Path | None = None) -> Path | None:
    """Write challenge results to ``<log_dir>/<challenge_name>/``.

    Creates four files:
    - ``log.jsonl``    -- full step log in JSON Lines format
    - ``output.mm``    -- final generated Mumei code
    - ``metrics.json`` -- Metrics.to_dict() output
    - ``summary.md``   -- human-readable Markdown summary

    Args:
        result: The result dict from :func:`run_challenge`.
        log_dir: Base directory for results.  Defaults to
                 ``examples/challenges/results/``.

    Returns:
        Path to the challenge results directory, or None on skip.
    """
    log_data = result.get("log")
    if not log_data:
        return None

    challenge_name = result.get("challenge_name", "unnamed")
    base_dir = log_dir or DEFAULT_RESULTS_DIR
    results_dir = base_dir / challenge_name
    results_dir.mkdir(parents=True, exist_ok=True)

    now_iso = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()

    # log.jsonl -- each step as a JSON Lines entry
    log_path = results_dir / "log.jsonl"
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({
            "step": "spec",
            "timestamp": now_iso,
            "challenge_name": challenge_name,
            "spec": log_data.get("spec"),
        }, ensure_ascii=False) + "\n")
        f.write(json.dumps({
            "step": "generate",
            "timestamp": now_iso,
            "verified": log_data.get("verified", False),
            "elapsed_seconds": log_data.get("elapsed_seconds"),
            "metrics": log_data.get("metrics"),
        }, ensure_ascii=False) + "\n")

    # output.mm -- final generated code
    code = result.get("code", "")
    output_path = results_dir / "output.mm"
    output_path.write_text(code, encoding="utf-8")

    # metrics.json -- Metrics.to_dict()
    metrics_data = log_data.get("metrics", {})
    metrics_path = results_dir / "metrics.json"
    metrics_path.write_text(
        json.dumps(metrics_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # summary.md -- human-readable summary
    summary_path = results_dir / "summary.md"
    verified = log_data.get("verified", False)
    elapsed = log_data.get("elapsed_seconds", 0)
    status_str = "PASSED" if verified else "FAILED"
    spec = log_data.get("spec", {})

    atoms_section = ""
    if "atoms" in spec:
        atom_names = [a.get("name", "<unnamed>") for a in spec["atoms"]]
        atoms_section = f"- **Atoms**: {', '.join(atom_names)}\n"

    total_attempts = metrics_data.get("total_attempts", 0)
    successes = metrics_data.get("successes", 0)

    summary_md = (
        f"# {challenge_name} \u2014 Zero-Human Challenge Result\n"
        f"\n"
        f"- **Status**: {status_str}\n"
        f"- **Elapsed**: {elapsed:.1f}s\n"
        f"{atoms_section}"
        f"- **Total attempts**: {total_attempts}\n"
        f"- **Successes**: {successes}\n"
        f"\n"
        f"## Spec\n"
        f"\n"
        f"```json\n"
        f"{json.dumps(spec, indent=2, ensure_ascii=False)}\n"
        f"```\n"
        f"\n"
        f"## Generated Code\n"
        f"\n"
        f"```mumei\n"
        f"{code}\n"
        f"```\n"
        f"\n"
        f"## Metrics\n"
        f"\n"
        f"```json\n"
        f"{json.dumps(metrics_data, indent=2, ensure_ascii=False)}\n"
        f"```\n"
    )
    summary_path.write_text(summary_md, encoding="utf-8")

    print(f"  Results written to: {results_dir}/")
    return results_dir


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Zero-Human Challenge Runner",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "spec_path",
        nargs="?",
        default=None,
        help="Path to a single challenge spec JSON",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="Run all challenge specs in examples/challenges/",
    )
    parser.add_argument(
        "--log-dir",
        type=str,
        default=None,
        help="Directory for result output (default: examples/challenges/results/)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate specs only without LLM generation or mumei verification",
    )
    args = parser.parse_args()

    log_dir = Path(args.log_dir) if args.log_dir else None

    specs: list[str] = []
    if args.all:
        discovered = discover_specs()
        if not discovered:
            print("No challenge spec files found in examples/challenges/")
            sys.exit(1)
        specs = [str(p) for p in discovered]
        print(f"Discovered {len(specs)} challenge spec(s):")
        for s in specs:
            print(f"  - {s}")
        print()
    else:
        specs = [args.spec_path]

    results: list[dict] = []
    for spec_path in specs:
        result = run_challenge(spec_path, dry_run=args.dry_run)
        if not args.dry_run:
            _write_results(result, log_dir=log_dir)
        results.append(result)
        print()

    # Final summary
    print("=" * 60)
    print("Zero-Human Challenge — Final Summary")
    print("=" * 60)
    total = len(results)
    validated = sum(1 for r in results if r["steps"].get("spec_validation"))
    generated = sum(1 for r in results if r["steps"].get("generate"))
    verified = sum(1 for r in results if r["steps"].get("verify"))
    errored = sum(1 for r in results if r["errors"])

    print(f"  Total challenges: {total}")
    print(f"  Specs validated:  {validated}/{total}")
    if not args.dry_run:
        print(f"  Code generated:   {generated}/{total}")
        print(f"  Verified:         {verified}/{total}")
    if errored:
        print(f"  Errors:           {errored}")
    print("=" * 60)

    # Exit code
    if errored:
        sys.exit(2)
    elif args.dry_run:
        sys.exit(0)
    elif verified == total:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
