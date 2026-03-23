#!/usr/bin/env python3
"""E2E Demo: Specification -> Verified Mumei Code.

This script demonstrates the full mumei-agent pipeline:
  1. Read a specification (JSON) describing the desired atom
  2. Call generate_code() to produce .mm source via LLM
  3. Write generated code to a temporary file
  4. Verify the generated code with mumei verify --json
  5. Report results with success/failure summary

Usage:
    python -m examples.run_e2e_demo [spec_path] [--dry-run]

    spec_path defaults to examples/e2e_demo_spec.json
    --dry-run  skips LLM generation and mumei verification (validates spec only)
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path


def _mumei_available(mumei_bin: str = "mumei") -> bool:
    """Check whether the mumei binary is available.

    Handles both simple binary names (looked up on PATH) and compound
    commands like ``cargo run --manifest-path ... --``.
    """
    first_token = mumei_bin.split()[0] if mumei_bin else "mumei"
    return shutil.which(first_token) is not None


def validate_spec(spec: dict) -> list[str]:
    """Validate a spec dict and return a list of error messages (empty = valid)."""
    errors: list[str] = []
    if not spec.get("name"):
        errors.append("spec must have a non-empty 'name' field")
    params = spec.get("params", spec.get("inputs", []))
    if not isinstance(params, list):
        errors.append("'params' must be a list")
    else:
        for i, p in enumerate(params):
            if not isinstance(p, dict) or "name" not in p:
                errors.append(f"params[{i}] must be a dict with at least a 'name' key")
    constraints = spec.get("constraints", {})
    if constraints and not isinstance(constraints, dict):
        errors.append("'constraints' must be a dict if provided")
    effects = spec.get("effects", [])
    if not isinstance(effects, list):
        errors.append("'effects' must be a list if provided")
    return errors


def run_e2e(spec_path: str | None = None, dry_run: bool = False) -> dict:
    """Run the E2E demo pipeline.

    Args:
        spec_path: Path to the spec JSON file.
        dry_run: If True, validate spec only without LLM or mumei invocation.

    Returns:
        A result dict with keys: spec, code, verified, dry_run, errors.
    """
    if spec_path is None:
        spec_path = str(Path(__file__).parent / "e2e_demo_spec.json")

    # Load spec
    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)

    result: dict = {
        "spec": spec,
        "code": "",
        "verified": False,
        "dry_run": dry_run,
        "errors": [],
    }

    print(f"=== E2E Demo: {spec.get('name', 'unnamed')} ===")
    print(f"Description: {spec.get('description', 'N/A')}")
    print(f"Effects: {spec.get('effects', [])}")
    print(f"Constraints: {json.dumps(spec.get('constraints', {}), indent=2)}")
    print()

    # Validate spec
    validation_errors = validate_spec(spec)
    if validation_errors:
        for err in validation_errors:
            print(f"VALIDATION ERROR: {err}")
        result["errors"] = validation_errors
        return result

    print("Spec validation: OK")

    if dry_run:
        print()
        print("=" * 60)
        print("RESULT: DRY RUN (spec validated, no generation/verification)")
        print("=" * 60)
        return result

    # Import agent modules (deferred to avoid import errors in dry-run mode)
    from agent.config import AgentConfig
    from agent.metrics import Metrics
    from agent.mumei_client import MumeiClient
    from agent.strategies.generate_strategy import generate_code

    # Load config
    config = AgentConfig()
    client = config.create_client()
    model = config.model

    # Optional: MumeiClient for real verification
    mumei_client: MumeiClient | None = None
    if config.mumei_bin and _mumei_available(config.mumei_bin):
        mumei_client = MumeiClient(config.mumei_bin)
        print(f"Using mumei binary: {config.mumei_bin}")
    else:
        print("No mumei binary available -- running in generation-only mode")
    print()

    # Run pipeline
    metrics = Metrics()
    code, verified = generate_code(
        client=client,
        model=model,
        spec=spec,
        config_max_retries=5,
        mumei_client=mumei_client,
        metrics=metrics,
    )

    result["code"] = code
    result["verified"] = verified

    # Write generated code to temp file for inspection
    if code:
        tmp_dir = Path(tempfile.mkdtemp(prefix="mumei_e2e_"))
        output_file = tmp_dir / f"{spec.get('name', 'output')}.mm"
        output_file.write_text(code, encoding="utf-8")
        print(f"Generated code written to: {output_file}")
        result["output_file"] = str(output_file)

    # Report
    print()
    print("=" * 60)
    if mumei_client is None:
        status = "GENERATED (no verifier -- verification skipped)"
    elif verified:
        status = "VERIFIED"
    else:
        status = "NOT VERIFIED (failed verification)"
    print(f"RESULT: {status}")
    print("=" * 60)
    print()
    print("Generated code:")
    print("-" * 40)
    print(code)
    print("-" * 40)
    print()
    print(f"Metrics: {metrics.to_json()}")

    return result


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="E2E Demo: Specification -> Verified Mumei Code",
    )
    parser.add_argument(
        "spec_path",
        nargs="?",
        default=None,
        help="Path to spec JSON file (default: examples/e2e_demo_spec.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate spec only without LLM generation or mumei verification",
    )
    args = parser.parse_args()
    result = run_e2e(spec_path=args.spec_path, dry_run=args.dry_run)

    # Exit code: 2 for errors, 0 for success/dry-run, 1 otherwise
    if result["errors"]:
        sys.exit(2)
    elif result["dry_run"] or result["verified"]:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
