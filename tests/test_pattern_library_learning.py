"""Tests for P6-B: Pattern Library Learning Extension."""
import json
from pathlib import Path
from unittest.mock import MagicMock

from agent.metrics import Metrics
from agent.pattern_library import PatternLibrary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pattern_library(tmp_path: Path, patterns: dict | None = None) -> PatternLibrary:
    """Create a PatternLibrary with a temporary storage path."""
    storage = tmp_path / "patterns.json"
    if patterns is not None:
        storage.write_text(json.dumps(patterns, ensure_ascii=False), encoding="utf-8")
    lib = PatternLibrary(storage_path=storage)
    return lib


def _mock_mumei_client(verify_success: bool = True) -> MagicMock:
    """Create a mock MumeiClient."""
    client = MagicMock()
    client.verify.return_value = {
        "success": verify_success,
        "report": {"status": "ok"} if verify_success else {"status": "failed"},
        "stdout": "",
        "stderr": "" if verify_success else "Verification failed",
    }
    return client


SOURCE_BEFORE = (
    "atom safe_divide(a: i64, b: i64)\n"
    "    requires: true;\n"
    "    ensures: result == a / b;\n"
    "    body: a / b;\n"
)

SOURCE_AFTER = (
    "atom safe_divide(a: i64, b: i64)\n"
    "    requires: b != 0;\n"
    "    ensures: result == a / b;\n"
    "    body: a / b;\n"
)

REPORT = {
    "status": "failed",
    "failure_type": "precondition_violated",
    "violation_type": "precondition_violated",
    "atom": "safe_divide",
    "counterexample": {"a": "10", "b": "0"},
    "suggestion": "Add requires: b != 0",
}


# ---------------------------------------------------------------------------
# try_pattern_fix() tests
# ---------------------------------------------------------------------------

def test_try_pattern_fix_returns_none_when_no_patterns(tmp_path):
    """Test that try_pattern_fix returns None when no patterns exist."""
    lib = _make_pattern_library(tmp_path)
    mumei = _mock_mumei_client()

    result = lib.try_pattern_fix("precondition_violated", SOURCE_BEFORE, REPORT, mumei)
    assert result is None


def test_try_pattern_fix_applies_matching_pattern(tmp_path):
    """Test that try_pattern_fix applies a matching pattern and returns fixed code."""
    lib = _make_pattern_library(tmp_path)

    # Record a pattern
    lib.record(
        violation_type="precondition_violated",
        failure_type="precondition_violated",
        source_before=SOURCE_BEFORE,
        source_after=SOURCE_AFTER,
        report=REPORT,
        fix_method="rule_based",
    )

    # The source to fix is identical to source_before
    mumei = _mock_mumei_client(verify_success=True)
    result = lib.try_pattern_fix("precondition_violated", SOURCE_BEFORE, REPORT, mumei)

    assert result is not None
    assert "b != 0" in result


def test_try_pattern_fix_returns_none_on_verify_failure(tmp_path):
    """Test that try_pattern_fix returns None if verification fails."""
    lib = _make_pattern_library(tmp_path)

    lib.record(
        violation_type="precondition_violated",
        failure_type="precondition_violated",
        source_before=SOURCE_BEFORE,
        source_after=SOURCE_AFTER,
        report=REPORT,
        fix_method="llm",
    )

    mumei = _mock_mumei_client(verify_success=False)
    result = lib.try_pattern_fix("precondition_violated", SOURCE_BEFORE, REPORT, mumei)

    assert result is None


def test_try_pattern_fix_returns_none_for_wrong_violation_type(tmp_path):
    """Test that try_pattern_fix returns None if no patterns match the violation type."""
    lib = _make_pattern_library(tmp_path)

    lib.record(
        violation_type="effect_mismatch",
        failure_type="effect_mismatch",
        source_before=SOURCE_BEFORE,
        source_after=SOURCE_AFTER,
        report=REPORT,
        fix_method="llm",
    )

    mumei = _mock_mumei_client(verify_success=True)
    result = lib.try_pattern_fix("precondition_violated", SOURCE_BEFORE, REPORT, mumei)

    assert result is None


# ---------------------------------------------------------------------------
# Success rate ranking tests
# ---------------------------------------------------------------------------

def test_success_rate_ranking(tmp_path):
    """Test that patterns with higher success rate are tried first."""
    patterns = {
        "precondition_violated": [
            {
                "violation_type": "precondition_violated",
                "failure_type": "precondition_violated",
                "source_before": "a",
                "source_after": "b",
                "report_summary": {"counterexample": {"a": "1"}},
                "fix_method": "llm",
                "content_hash": "aaa",
                "applied_count": 10,
                "success_count": 2,  # 20% success rate
            },
            {
                "violation_type": "precondition_violated",
                "failure_type": "precondition_violated",
                "source_before": "c",
                "source_after": "d",
                "report_summary": {"counterexample": {"a": "1"}},
                "fix_method": "llm",
                "content_hash": "bbb",
                "applied_count": 5,
                "success_count": 4,  # 80% success rate
            },
        ],
    }
    lib = _make_pattern_library(tmp_path, patterns)

    results = lib.lookup("precondition_violated", max_results=2)
    # Higher success rate should come first
    assert results[0]["content_hash"] == "bbb"
    assert results[1]["content_hash"] == "aaa"


def test_success_rate_ranking_zero_applied(tmp_path):
    """Test that patterns with 0 applied_count sort after proven ones."""
    patterns = {
        "precondition_violated": [
            {
                "violation_type": "precondition_violated",
                "failure_type": "precondition_violated",
                "source_before": "a",
                "source_after": "b",
                "report_summary": {},
                "fix_method": "llm",
                "content_hash": "aaa",
                "applied_count": 0,
                "success_count": 0,  # 0% — never applied
            },
            {
                "violation_type": "precondition_violated",
                "failure_type": "precondition_violated",
                "source_before": "c",
                "source_after": "d",
                "report_summary": {},
                "fix_method": "llm",
                "content_hash": "bbb",
                "applied_count": 3,
                "success_count": 2,  # 66% success rate
            },
        ],
    }
    lib = _make_pattern_library(tmp_path, patterns)

    results = lib.lookup("precondition_violated", max_results=2)
    assert results[0]["content_hash"] == "bbb"
    assert results[1]["content_hash"] == "aaa"


# ---------------------------------------------------------------------------
# applied_count / success_count persistence tests
# ---------------------------------------------------------------------------

def test_applied_count_incremented_on_try(tmp_path):
    """Test that applied_count is incremented when a pattern is tried."""
    lib = _make_pattern_library(tmp_path)

    lib.record(
        violation_type="precondition_violated",
        failure_type="precondition_violated",
        source_before=SOURCE_BEFORE,
        source_after=SOURCE_AFTER,
        report=REPORT,
        fix_method="llm",
    )

    # Verify the initial counts
    pattern = lib.patterns["precondition_violated"][0]
    assert pattern["applied_count"] == 0
    assert pattern["success_count"] == 0

    # Try and fail
    mumei = _mock_mumei_client(verify_success=False)
    lib.try_pattern_fix("precondition_violated", SOURCE_BEFORE, REPORT, mumei)

    # applied_count should be incremented
    pattern = lib.patterns["precondition_violated"][0]
    assert pattern["applied_count"] == 1
    assert pattern["success_count"] == 0


def test_success_count_incremented_on_success(tmp_path):
    """Test that both applied_count and success_count are incremented on success."""
    lib = _make_pattern_library(tmp_path)

    lib.record(
        violation_type="precondition_violated",
        failure_type="precondition_violated",
        source_before=SOURCE_BEFORE,
        source_after=SOURCE_AFTER,
        report=REPORT,
        fix_method="llm",
    )

    mumei = _mock_mumei_client(verify_success=True)
    result = lib.try_pattern_fix("precondition_violated", SOURCE_BEFORE, REPORT, mumei)

    assert result is not None
    pattern = lib.patterns["precondition_violated"][0]
    assert pattern["applied_count"] == 1
    assert pattern["success_count"] == 1


def test_counts_persisted_to_disk(tmp_path):
    """Test that updated counts are persisted to disk."""
    lib = _make_pattern_library(tmp_path)

    lib.record(
        violation_type="precondition_violated",
        failure_type="precondition_violated",
        source_before=SOURCE_BEFORE,
        source_after=SOURCE_AFTER,
        report=REPORT,
        fix_method="llm",
    )

    mumei = _mock_mumei_client(verify_success=True)
    lib.try_pattern_fix("precondition_violated", SOURCE_BEFORE, REPORT, mumei)

    # Reload from disk
    lib2 = PatternLibrary(storage_path=lib.storage_path)
    pattern = lib2.patterns["precondition_violated"][0]
    assert pattern["applied_count"] == 1
    assert pattern["success_count"] == 1


# ---------------------------------------------------------------------------
# Backward compatibility tests
# ---------------------------------------------------------------------------

def test_backward_compat_missing_count_fields(tmp_path):
    """Test that patterns without applied_count/success_count fields default to 0."""
    patterns = {
        "precondition_violated": [
            {
                "violation_type": "precondition_violated",
                "failure_type": "precondition_violated",
                "source_before": "old code",
                "source_after": "new code",
                "report_summary": {},
                "fix_method": "llm",
                "content_hash": "abc123",
                # No applied_count or success_count
            },
        ],
    }
    lib = _make_pattern_library(tmp_path, patterns)

    results = lib.lookup("precondition_violated")
    assert len(results) == 1
    # Missing fields should be treated as 0 via .get() defaults
    p = results[0]
    assert p.get("applied_count", 0) == 0
    assert p.get("success_count", 0) == 0


def test_record_includes_count_fields(tmp_path):
    """Test that newly recorded patterns have count fields set to 0."""
    lib = _make_pattern_library(tmp_path)

    lib.record(
        violation_type="effect_mismatch",
        failure_type="effect_mismatch",
        source_before="old",
        source_after="new",
        report={"violation_type": "effect_mismatch"},
        fix_method="llm",
    )

    pattern = lib.patterns["effect_mismatch"][0]
    assert pattern["applied_count"] == 0
    assert pattern["success_count"] == 0


# ---------------------------------------------------------------------------
# Metrics integration tests
# ---------------------------------------------------------------------------

def test_metrics_pattern_attempt():
    """Test recording a pattern attempt."""
    m = Metrics()
    m.record_pattern_attempt("precondition_violated")
    assert m.pattern_attempts == 1
    assert m.pattern_successes == 0


def test_metrics_pattern_success():
    """Test recording a pattern success."""
    m = Metrics()
    m.record_pattern_success("precondition_violated")
    assert m.pattern_successes == 1
    assert m.total_attempts == 1
    assert m.successes == 1


def test_metrics_pattern_in_to_dict():
    """Test that pattern metrics appear in to_dict output."""
    m = Metrics()
    m.record_pattern_attempt("x")
    m.record_pattern_success("x")
    d = m.to_dict()
    assert d["pattern_attempts"] == 1
    assert d["pattern_successes"] == 1


def test_metrics_pattern_success_rate():
    """Test pattern success rate calculation."""
    m = Metrics()
    assert m.pattern_success_rate == 0.0
    m.record_pattern_attempt("x")
    m.record_pattern_attempt("x")
    m.record_pattern_success("x")
    # 1 success out of 2+1=3 attempts? No — pattern_attempts tracks
    # failed attempts only via record_pattern_attempt, and
    # record_pattern_success also increments total pattern_successes.
    # pattern_attempts=2, pattern_successes=1 → rate = 0.5
    assert m.pattern_success_rate == 0.5
