#!/usr/bin/env python3
"""E2E Demo: Specification → Verified Mumei Code.

This script demonstrates the full mumei-agent pipeline:
  1. Read a specification (JSON) describing the desired atom
  2. Call generate_code() to produce .mm source via LLM
  3. Verify the generated code with mumei verify --json
  4. If verification passes, report success

Usage:
    python -m examples.run_e2e_demo [spec_path]

    spec_path defaults to examples/e2e_demo_spec.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from agent.config import AgentConfig
from agent.metrics import Metrics
from agent.mumei_client import MumeiClient
from agent.strategies.generate_strategy import generate_code


def main(spec_path: str | None = None) -> None:
    """Run the E2E demo pipeline."""
    if spec_path is None:
        spec_path = str(Path(__file__).parent / "e2e_demo_spec.json")

    # Load spec
    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)

    print(f"=== E2E Demo: {spec.get('name', 'unnamed')} ===")
    print(f"Description: {spec.get('description', 'N/A')}")
    print(f"Effects: {spec.get('effects', [])}")
    print(f"Constraints: {json.dumps(spec.get('constraints', {}), indent=2)}")
    print()

    # Load config
    config = AgentConfig()
    client = config.create_client()
    model = config.model

    # Optional: MumeiClient for real verification
    mumei_client: MumeiClient | None = None
    if config.mumei_bin:
        mumei_client = MumeiClient(config.mumei_bin)
        print(f"Using mumei binary: {config.mumei_bin}")
    else:
        print("No mumei binary configured — running in generation-only mode")
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

    # Report
    print("=" * 60)
    if mumei_client is None:
        print("RESULT: GENERATED (no verifier — verification skipped)")
    elif verified:
        print("RESULT: VERIFIED")
    else:
        print("RESULT: NOT VERIFIED (failed verification)")
    print("=" * 60)
    print()
    print("Generated code:")
    print("-" * 40)
    print(code)
    print("-" * 40)
    print()
    print(f"Metrics: {metrics.to_json()}")


if __name__ == "__main__":
    spec_arg = sys.argv[1] if len(sys.argv) > 1 else None
    main(spec_arg)
