"""End-to-end integration tests using the mock mumei binary.

Each test exercises the full verify -> fix -> re-verify loop for a single
violation type.  The mock binary (``tests/fixtures/mock_mumei.py``) returns
canned failure reports on the first call and detects "fixed" patterns on the
second call to return success.

All tests in this module are marked with ``@pytest.mark.integration`` so
that CI can exclude them with ``-m "not integration"``.  Run locally with::

    pytest tests/test_integration_e2e.py -v
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from agent.mumei_client import MumeiClient
from agent.strategies.fix_strategy import get_fix

# ---------------------------------------------------------------------------
# Violation fixtures — maps violation name to:
#   - fixture_file: .mm fixture that triggers the violation
#   - fixed_source: source code that the mock recognises as "fixed"
# ---------------------------------------------------------------------------

VIOLATION_FIXTURES: dict[str, dict[str, str]] = {
    "precondition_violated": {
        "fixture_file": "precondition_violated.mm",
        "fixed_source": (
            "atom safe_divide(a: i64, b: i64) -> i64\n"
            "    requires: b != 0;\n"
            "    ensures: result == a / b;\n"
            "    body: a / b;\n"
        ),
    },
    "postcondition_violated": {
        "fixture_file": "postcondition_violated.mm",
        "fixed_source": (
            "atom add_positive(x: i64) -> i64\n"
            "    requires: x > 0;\n"
            "    ensures: result > 0;\n"
            "    body: x;\n"
        ),
    },
    "division_by_zero": {
        "fixture_file": "division_by_zero.mm",
        "fixed_source": (
            "atom unsafe_div(a: i64, b: i64) -> i64\n"
            "    requires: b != 0;\n"
            "    ensures: result == a / b;\n"
            "    body: a / b;\n"
        ),
    },
    "linearity_violated": {
        "fixture_file": "linearity_fail.mm",
        "fixed_source": (
            "atom use_twice(x: i64) -> i64\n"
            "    body: {\n"
            "        let a = clone(x);\n"
            "        let b = x;\n"
            "        a + b\n"
            "    };\n"
        ),
    },
    "invariant_violated": {
        "fixture_file": "invariant_violated.mm",
        "fixed_source": (
            "atom check_bounds(x: i64) -> i64\n"
            "    requires: x >= 0 && x <= 10;\n"
            "    ensures: result == x;\n"
            "    body: x;\n"
        ),
    },
    "temporal_effect_violated": {
        "fixture_file": "temporal_effect_fail.mm",
        "fixed_source": (
            "atom bad_file_usage(path: Str) -> i64\n"
            "    effects: [FileRead, FileWrite];\n"
            "    body: {\n"
            "        let h = perform FileRead.open(path);\n"
            "        perform FileWrite.write(h, \"data\");\n"
            "        perform FileWrite.close(h);\n"
            "        0\n"
            "    };\n"
        ),
    },
    "effect_mismatch": {
        "fixture_file": "effect_mismatch.mm",
        "fixed_source": (
            "atom write_log(msg: i64) -> i64\n"
            "    effects: [Log, FileWrite];\n"
            "    requires: msg >= 0;\n"
            "    ensures: result == msg;\n"
            "    body: {\n"
            "        perform FileWrite.write(msg);\n"
            "        msg\n"
            "    };\n"
        ),
    },
    "effect_propagation": {
        "fixture_file": "effect_propagation.mm",
        "fixed_source": (
            "atom write_log(msg: i64) -> i64\n"
            "    effects: [Log, FileWrite];\n"
            "    requires: msg >= 0;\n"
            "    ensures: result == msg;\n"
            "    body: {\n"
            "        perform FileWrite.write(msg);\n"
            "        msg\n"
            "    };\n"
            "\n"
            "atom main_handler(msg: i64) -> i64\n"
            "    effects: [Log, FileWrite];\n"
            "    requires: msg >= 0;\n"
            "    ensures: result == msg;\n"
            "    body: write_log(msg);\n"
        ),
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _write_temp(source: str, suffix: str = ".mm") -> Path:
    """Write *source* to a named temp file and return its path."""
    fd = tempfile.NamedTemporaryFile(suffix=suffix, delete=False, mode="w")
    fd.write(source)
    fd.close()
    return Path(fd.name)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestMockVerifyFailure:
    """Verify that the mock binary returns a failure report for each fixture."""

    @pytest.mark.parametrize(
        "violation_type",
        list(VIOLATION_FIXTURES.keys()),
    )
    def test_verify_returns_failure(
        self,
        mumei_mock_e2e_client: MumeiClient,
        violation_type: str,
    ):
        fixture = VIOLATION_FIXTURES[violation_type]
        source_path = FIXTURES_DIR / fixture["fixture_file"]
        result = mumei_mock_e2e_client.verify(str(source_path))
        assert result["success"] is False, (
            f"Expected failure for {violation_type}, got success"
        )
        report = result["report"]
        assert report.get("status") == "failed"


@pytest.mark.integration
class TestMockVerifyFixedSuccess:
    """Verify that the mock binary returns success for 'fixed' source code."""

    @pytest.mark.parametrize(
        "violation_type",
        list(VIOLATION_FIXTURES.keys()),
    )
    def test_verify_fixed_returns_success(
        self,
        mumei_mock_e2e_client: MumeiClient,
        violation_type: str,
    ):
        fixture = VIOLATION_FIXTURES[violation_type]
        tmp = _write_temp(fixture["fixed_source"])
        try:
            result = mumei_mock_e2e_client.verify(str(tmp))
            assert result["success"] is True, (
                f"Expected success for fixed {violation_type}, got failure: "
                f"{result.get('report')}"
            )
        finally:
            tmp.unlink(missing_ok=True)


@pytest.mark.integration
class TestE2EHealLoop:
    """Full verify -> fix -> re-verify loop using the mock mumei binary."""

    @pytest.mark.parametrize(
        "violation_type",
        list(VIOLATION_FIXTURES.keys()),
    )
    def test_heal_loop(
        self,
        mumei_mock_e2e_client: MumeiClient,
        mock_openai_client,
        violation_type: str,
    ):
        fixture = VIOLATION_FIXTURES[violation_type]
        source_path = FIXTURES_DIR / fixture["fixture_file"]
        original_source = source_path.read_text()

        # Step 1: Verify original — should fail.
        result1 = mumei_mock_e2e_client.verify(str(source_path))
        assert result1["success"] is False

        report = result1["report"]
        error_log = result1.get("stderr", "Verification failed")

        # Step 2: Get fix via mocked OpenAI (returns the "fixed" source).
        fixed_source = fixture["fixed_source"]
        response_text = f"```mumei\n{fixed_source}```"
        client = mock_openai_client(response_text)
        fix_result = get_fix(
            client, "test-model", original_source, error_log, report
        )
        assert len(fix_result) > 0, "Fix should produce non-empty output"

        # Step 3: Write fixed code and re-verify — should succeed.
        tmp = _write_temp(fixed_source)
        try:
            result2 = mumei_mock_e2e_client.verify(str(tmp))
            assert result2["success"] is True, (
                f"Re-verification should succeed for {violation_type}, "
                f"got: {result2.get('report')}"
            )
        finally:
            tmp.unlink(missing_ok=True)


@pytest.mark.integration
class TestMockCheck:
    """Verify the mock binary's ``check`` sub-command."""

    def test_check_existing_file(self, mumei_mock_e2e_client: MumeiClient):
        source_path = FIXTURES_DIR / "valid.mm"
        result = mumei_mock_e2e_client.check(str(source_path))
        assert result["success"] is True

    def test_check_nonexistent_file(self, mumei_mock_e2e_client: MumeiClient):
        result = mumei_mock_e2e_client.check("/tmp/nonexistent_file.mm")
        assert result["success"] is False
