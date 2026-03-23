"""Integration tests that exercise the real mumei binary.

Every test in this module is marked with ``@pytest.mark.integration`` so that
CI can exclude them with ``-m "not integration"``.  To run locally::

    MUMEI_BIN=mumei pytest -m integration -v

If ``MUMEI_BIN`` is not set the tests fall back to a plain ``mumei`` on
``$PATH``; if neither is found the entire module is skipped.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent.mumei_client import MumeiClient
from agent.strategies.fix_strategy import get_fix

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Maps each fixture file stem to the expected violation / failure type key
# that should appear in the verification report.
VIOLATION_FIXTURES: dict[str, list[str]] = {
    "precondition_fail": ["precondition_violated"],
    "postcondition_fail": ["postcondition_violated"],
    "division_by_zero": ["division_by_zero"],
    "linearity_fail": ["linearity_violated"],
    "temporal_effect_fail": ["temporal_effect_violated"],
    "effect_mismatch": ["effect_mismatch"],
}


def _violation_type(report: dict) -> str:
    """Extract the violation / failure type string from a verify report."""
    inner = report.get("report", {})
    return inner.get("violation_type", inner.get("failure_type", ""))


# ---------------------------------------------------------------------------
# Verification tests — one per fixture
# ---------------------------------------------------------------------------


class TestVerifyViolationFixtures:
    """Run ``mumei verify --json`` on each violation fixture and assert the
    returned report contains the expected failure type."""

    @pytest.mark.parametrize(
        "fixture_stem, expected_types",
        list(VIOLATION_FIXTURES.items()),
        ids=list(VIOLATION_FIXTURES.keys()),
    )
    def test_verify_detects_violation(
        self,
        real_mumei_client: MumeiClient,
        fixtures_dir: Path,
        fixture_stem: str,
        expected_types: list[str],
    ) -> None:
        source_path = fixtures_dir / f"{fixture_stem}.mm"
        assert source_path.exists(), f"Missing fixture: {source_path}"

        result = real_mumei_client.verify(str(source_path))

        # The binary should report a failure
        assert result["success"] is False, (
            f"Expected verification failure for {fixture_stem}, got success"
        )
        vtype = _violation_type(result)
        assert vtype in expected_types, (
            f"Expected one of {expected_types} for {fixture_stem}, got '{vtype}'"
        )


class TestVerifyValidFixture:
    """Ensure the valid.mm fixture passes verification."""

    def test_valid_passes(
        self,
        real_mumei_client: MumeiClient,
        fixtures_dir: Path,
    ) -> None:
        source_path = fixtures_dir / "valid.mm"
        assert source_path.exists()

        result = real_mumei_client.verify(str(source_path))
        assert result["success"] is True, (
            f"Expected valid.mm to pass verification: {result['stderr']}"
        )


# ---------------------------------------------------------------------------
# Self-healing loop integration (LLM mocked, mumei binary real)
# ---------------------------------------------------------------------------


def _mock_llm_client(fixed_code: str) -> MagicMock:
    """Return a MagicMock OpenAI client that yields *fixed_code*."""
    client = MagicMock()
    message = MagicMock()
    message.content = f"```mumei\n{fixed_code}\n```"
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    client.chat.completions.create.return_value = response
    return client


class TestSelfHealingLoop:
    """Integration: call ``get_fix()`` with a mocked LLM but a *real* mumei
    binary to verify that the self-healing loop can produce code that passes
    ``mumei check``."""

    def test_precondition_fix_generates_code(
        self,
        real_mumei_client: MumeiClient,
        fixtures_dir: Path,
    ) -> None:
        """get_fix() returns non-empty code for a precondition violation."""
        source_path = fixtures_dir / "precondition_fail.mm"
        source_code = source_path.read_text(encoding="utf-8")

        # First, get the real verification report
        verify_result = real_mumei_client.verify(str(source_path))
        assert verify_result["success"] is False

        report = verify_result["report"] or {}
        error_log = verify_result["stdout"] + verify_result["stderr"]

        # Provide a valid fix that the mocked LLM "produces"
        fixed_code = (
            "atom safe_divide(a: i64, b: i64) -> i64\n"
            "    requires: b != 0;\n"
            "    ensures: result == a / b;\n"
            "    body: a / b;\n"
            "\n"
            "atom main() -> i64\n"
            "    body: safe_divide(10, 1);\n"
        )
        llm_client = _mock_llm_client(fixed_code)

        result = get_fix(
            llm_client,
            "test-model",
            source_code,
            error_log,
            report,
        )

        assert len(result) > 0, "get_fix() should return non-empty code"

    def test_fixed_code_passes_check(
        self,
        real_mumei_client: MumeiClient,
    ) -> None:
        """A known-good fix for the precondition fixture passes mumei check."""
        fixed_code = (
            "atom safe_divide(a: i64, b: i64) -> i64\n"
            "    requires: b != 0;\n"
            "    ensures: result == a / b;\n"
            "    body: a / b;\n"
            "\n"
            "atom main() -> i64\n"
            "    body: safe_divide(10, 1);\n"
        )
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".mm", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(fixed_code)
            tmp_path = tmp.name

        try:
            check_result = real_mumei_client.check(tmp_path)
            assert check_result["success"] is True, (
                f"Fixed code should pass mumei check: {check_result['stderr']}"
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# mumei check (parse-only) sanity test
# ---------------------------------------------------------------------------


class TestMumeiCheck:
    """Verify that ``mumei check`` works on well-formed fixtures."""

    @pytest.mark.parametrize(
        "fixture_name",
        [
            "precondition_fail.mm",
            "postcondition_fail.mm",
            "division_by_zero.mm",
            "valid.mm",
        ],
    )
    def test_check_parses_fixture(
        self,
        real_mumei_client: MumeiClient,
        fixtures_dir: Path,
        fixture_name: str,
    ) -> None:
        """All fixtures should at least parse successfully."""
        source_path = fixtures_dir / fixture_name
        result = real_mumei_client.check(str(source_path))
        assert result["success"] is True, (
            f"{fixture_name} should parse: {result['stderr']}"
        )
