"""Shared test fixtures for mumei-agent integration tests."""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from agent.mumei_client import MumeiClient


# ---------------------------------------------------------------------------
# Directory containing .mm fixture files
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Sample report.json data for each violation / failure type
# ---------------------------------------------------------------------------

SAMPLE_REPORTS: dict[str, dict[str, Any]] = {
    "precondition_violated": {
        "status": "failed",
        "failure_type": "precondition_violated",
        "atom": "safe_divide",
        "reason": "Division by zero possible",
        "counterexample": {"a": "10", "b": "0"},
        "semantic_feedback": {
            "violated_constraints": [
                {
                    "param": "b",
                    "type": "i64",
                    "constraint": "b != 0",
                    "explanation": "Divisor must not be zero",
                    "sub_constraints": [
                        {"constraint": "b >= 0", "satisfied": True},
                        {"constraint": "b != 0", "satisfied": False},
                    ],
                }
            ],
        },
        "span": {"file": "math.mm", "line": 3, "col": 1},
        "suggestion": "Add requires: b != 0",
    },
    "postcondition_violated": {
        "status": "failed",
        "failure_type": "postcondition_violated",
        "atom": "add_positive",
        "counterexample": {"x": "0"},
        "semantic_feedback": {
            "violated_constraints": [
                {
                    "param": "x",
                    "type": "i64",
                    "constraint": "result > 0",
                    "explanation": "Result must be positive",
                }
            ],
        },
        "span": {"file": "math.mm", "line": 10, "col": 1},
        "suggestion": "Ensure body returns a positive value",
    },
    "division_by_zero": {
        "status": "failed",
        "failure_type": "division_by_zero",
        "atom": "unsafe_div",
        "semantic_feedback": {
            "counter_example": {"dividend": "10", "divisor": "0"},
        },
        "counterexample": {"a": "10", "b": "0"},
    },
    "linearity_violated": {
        "status": "failed",
        "failure_type": "linearity_violated",
        "atom": "use_twice",
        "semantic_feedback": {
            "violations": [
                {"description": "Variable 'x' used after move"},
            ],
        },
    },
    "invariant_violated": {
        "status": "failed",
        "failure_type": "invariant_violated",
        "atom": "check_bounds",
        "semantic_feedback": {
            "conflicting_constraints": ["x > 10", "x < 5"],
            "raw_unsat_core": ["(> x 10)", "(< x 5)"],
            "structured_unsat_core": [
                {
                    "constraint_type": "requires",
                    "param": None,
                    "type_name": None,
                    "field": None,
                    "description": "Precondition (requires)",
                },
                {
                    "constraint_type": "refined_type",
                    "param": "x",
                    "type_name": "Nat",
                    "field": None,
                    "description": "x >= 0",
                },
            ],
        },
    },
    "temporal_effect_violated": {
        "status": "failed",
        "failure_type": "temporal_effect_violated",
        "atom": "bad_file_usage",
        "semantic_feedback": {
            "temporal_violations": [
                {
                    "effect": "File",
                    "expected_state": "Open",
                    "actual_state": "Closed",
                    "operation": "write",
                }
            ],
        },
    },
    "effect_mismatch": {
        "status": "failed",
        "violation_type": "effect_mismatch",
        "atom": "write_log",
        "effect_violation": {
            "declared_effects": ["Log"],
            "required_effect": "FileWrite",
            "source_operation": "FileWrite.write",
            "resolution_paths": [
                {"strategy": "propagation", "description": "Add FileWrite to effects list"},
                {"strategy": "isolation", "description": "Remove the write call"},
            ],
        },
    },
    "effect_propagation": {
        "status": "failed",
        "violation_type": "effect_propagation",
        "effect_violation": {
            "caller": "main_handler",
            "callee": "write_log",
            "caller_effects": ["Log"],
            "callee_effects": ["Log", "FileWrite"],
            "missing_effects": ["FileWrite"],
            "resolution_paths": [],
        },
    },
    "with_structured_unsat_core": {
        "status": "failed",
        "failure_type": "precondition_violated",
        "atom": "bounded_add",
        "counterexample": {"a": "100", "b": "200"},
        "semantic_feedback": {
            "violated_constraints": [
                {
                    "param": "a",
                    "type": "i64",
                    "constraint": "a < 100",
                    "explanation": "a must be less than 100",
                }
            ],
            "structured_unsat_core": [
                {
                    "constraint_type": "requires",
                    "param": "a",
                    "type_name": None,
                    "field": None,
                    "description": "a >= 0 && a < 100",
                },
                {
                    "constraint_type": "requires",
                    "param": "b",
                    "type_name": None,
                    "field": None,
                    "description": "b >= 0 && b < 100",
                },
                {
                    "constraint_type": "ensures",
                    "param": None,
                    "type_name": None,
                    "field": None,
                    "description": "result == a + b",
                },
            ],
        },
        "suggestion": "Strengthen requires or weaken ensures",
    },
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def sample_reports() -> dict[str, dict[str, Any]]:
    """Return the full set of sample report.json data keyed by violation type."""
    return SAMPLE_REPORTS


@pytest.fixture()
def mock_openai_client():
    """Create a mock OpenAI client that returns a generic fix."""
    def _factory(response_text: str = "```mumei\natom fixed(x: i64) requires: x >= 0; ensures: result >= 0; body: x;\n```"):
        client = MagicMock()
        message = MagicMock()
        message.content = response_text
        choice = MagicMock()
        choice.message = message
        response = MagicMock()
        response.choices = [choice]
        client.chat.completions.create.return_value = response
        return client
    return _factory


@pytest.fixture()
def mock_mumei_client():
    """Create a mock MumeiClient."""
    def _factory(
        verify_success: bool = True,
        check_success: bool = True,
        verify_report: dict | None = None,
    ):
        client = MagicMock()
        client.verify.return_value = {
            "success": verify_success,
            "report": verify_report or ({"status": "ok"} if verify_success else {"status": "failed"}),
            "stdout": "",
            "stderr": "" if verify_success else "Verification failed",
        }
        client.check.return_value = {
            "success": check_success,
            "stdout": "",
            "stderr": "" if check_success else "Parse error",
        }
        client.infer_effects.return_value = {"analysis": {}}
        client.infer_contracts.return_value = {"analysis": {}}
        return client
    return _factory


@pytest.fixture()
def sample_source() -> str:
    """Return a sample Mumei source code string."""
    return (
        "atom safe_divide(a: i64, b: i64)\n"
        "    requires: b != 0;\n"
        "    ensures: result == a / b;\n"
        "    body: a / b;\n"
    )


# ---------------------------------------------------------------------------
# Real mumei binary fixtures (used by integration tests)
# ---------------------------------------------------------------------------

def _resolve_mumei_bin() -> str | None:
    """Return the mumei binary path, or *None* if unavailable.

    Resolution order:
      1. ``MUMEI_BIN`` environment variable (supports compound commands like
         ``cargo run --manifest-path … --``).
      2. Plain ``mumei`` looked up on ``$PATH``.
    """
    env_bin = os.environ.get("MUMEI_BIN", "").strip()
    if env_bin:
        first_token = env_bin.split()[0]
        if shutil.which(first_token):
            return env_bin
    if shutil.which("mumei"):
        return "mumei"
    return None


@pytest.fixture()
def mumei_bin() -> str:
    """Return the resolved mumei binary path or skip the test."""
    path = _resolve_mumei_bin()
    if path is None:
        pytest.skip("mumei binary not found (set MUMEI_BIN or install mumei)")
    return path


@pytest.fixture()
def real_mumei_client(mumei_bin: str) -> MumeiClient:
    """Provide a *real* MumeiClient backed by the mumei binary."""
    return MumeiClient(mumei_bin)


@pytest.fixture()
def fixtures_dir() -> Path:
    """Return the path to the tests/fixtures/ directory."""
    return FIXTURES_DIR
