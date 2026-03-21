"""Tests for RetryHistory and format_error_diff."""
from agent.strategies.retry_history import RetryAttempt, RetryHistory
from agent.prompts.report_formatter import format_error_diff


def _make_attempt(
    num: int,
    *,
    failure_type: str = "precondition_violated",
    counterexample: dict | None = None,
    report_extra: dict | None = None,
    diagnosis: dict | None = None,
) -> RetryAttempt:
    report: dict = {"failure_type": failure_type}
    if counterexample is not None:
        report["counterexample"] = counterexample
    if report_extra:
        report.update(report_extra)
    return RetryAttempt(
        attempt_number=num,
        source_code=f"source_{num}",
        error_log=f"error_{num}",
        report_data=report,
        diagnosis=diagnosis
        or {
            "root_cause": f"cause_{num}",
            "fix_approach": f"approach_{num}",
            "target_section": "requires",
        },
    )


# ---------- format_for_prompt ----------


class TestFormatForPrompt:
    def test_empty_history(self):
        h = RetryHistory()
        assert h.format_for_prompt() == ""

    def test_single_attempt(self):
        h = RetryHistory()
        h.add(_make_attempt(1))
        text = h.format_for_prompt()
        assert "Attempt 1" in text
        assert "cause_1" in text
        assert "approach_1" in text
        # No "SAME ERROR REPEATED" for first attempt
        assert "SAME ERROR REPEATED" not in text

    def test_two_attempts_different_errors(self):
        h = RetryHistory()
        h.add(
            _make_attempt(1, failure_type="precondition_violated", counterexample={"a": 0})
        )
        h.add(
            _make_attempt(2, failure_type="postcondition_violated", counterexample={"b": 1})
        )
        text = h.format_for_prompt()
        assert "Attempt 1" in text
        assert "Attempt 2" in text
        assert "SAME ERROR REPEATED" not in text

    def test_two_attempts_same_error(self):
        h = RetryHistory()
        h.add(
            _make_attempt(1, failure_type="precondition_violated", counterexample={"a": 0})
        )
        h.add(
            _make_attempt(2, failure_type="precondition_violated", counterexample={"a": 0})
        )
        text = h.format_for_prompt()
        assert "SAME ERROR REPEATED" in text

    def test_three_attempts(self):
        h = RetryHistory()
        for i in range(1, 4):
            h.add(_make_attempt(i, failure_type=f"type_{i}"))
        text = h.format_for_prompt()
        assert "Attempt 1" in text
        assert "Attempt 2" in text
        assert "Attempt 3" in text


# ---------- error_diff ----------


class TestErrorDiff:
    def test_fewer_than_two_attempts(self):
        h = RetryHistory()
        assert h.error_diff() == ""
        h.add(_make_attempt(1))
        assert h.error_diff() == ""

    def test_same_errors(self):
        h = RetryHistory()
        h.add(
            _make_attempt(1, failure_type="precondition_violated", counterexample={"a": 0})
        )
        h.add(
            _make_attempt(2, failure_type="precondition_violated", counterexample={"a": 0})
        )
        diff = h.error_diff()
        assert "UNCHANGED" in diff

    def test_different_errors(self):
        h = RetryHistory()
        h.add(
            _make_attempt(1, failure_type="precondition_violated", counterexample={"a": 0})
        )
        h.add(
            _make_attempt(2, failure_type="postcondition_violated", counterexample={"b": 5})
        )
        diff = h.error_diff()
        assert "CHANGED" in diff

    def test_partial_overlap_constraints(self):
        prev_report = {
            "failure_type": "precondition_violated",
            "semantic_feedback": {
                "violated_constraints": [
                    {"param": "a", "constraint": "a > 0"},
                    {"param": "b", "constraint": "b > 0"},
                ]
            },
        }
        curr_report = {
            "failure_type": "precondition_violated",
            "semantic_feedback": {
                "violated_constraints": [
                    {"param": "b", "constraint": "b > 0"},
                    {"param": "c", "constraint": "c != 0"},
                ]
            },
        }
        h = RetryHistory()
        h.add(
            RetryAttempt(
                attempt_number=1,
                source_code="s1",
                error_log="e1",
                report_data=prev_report,
                diagnosis={"root_cause": "x", "fix_approach": "y", "target_section": "z"},
            )
        )
        h.add(
            RetryAttempt(
                attempt_number=2,
                source_code="s2",
                error_log="e2",
                report_data=curr_report,
                diagnosis={"root_cause": "x", "fix_approach": "y", "target_section": "z"},
            )
        )
        diff = h.error_diff()
        assert "RESOLVED" in diff
        assert "NEW" in diff
        assert "a > 0" in diff
        assert "c != 0" in diff


# ---------- is_same_error_repeating ----------


class TestIsSameErrorRepeating:
    def test_empty(self):
        assert RetryHistory().is_same_error_repeating() is False

    def test_single_attempt(self):
        h = RetryHistory()
        h.add(_make_attempt(1))
        assert h.is_same_error_repeating() is False

    def test_two_same(self):
        h = RetryHistory()
        h.add(
            _make_attempt(1, failure_type="precondition_violated", counterexample={"a": 0})
        )
        h.add(
            _make_attempt(2, failure_type="precondition_violated", counterexample={"a": 0})
        )
        assert h.is_same_error_repeating() is True

    def test_two_different(self):
        h = RetryHistory()
        h.add(
            _make_attempt(1, failure_type="precondition_violated", counterexample={"a": 0})
        )
        h.add(
            _make_attempt(2, failure_type="postcondition_violated", counterexample={"a": 0})
        )
        assert h.is_same_error_repeating() is False

    def test_same_failure_different_counterexample(self):
        h = RetryHistory()
        h.add(
            _make_attempt(1, failure_type="precondition_violated", counterexample={"a": 0})
        )
        h.add(
            _make_attempt(2, failure_type="precondition_violated", counterexample={"a": 5})
        )
        assert h.is_same_error_repeating() is False


# ---------- format_error_diff (report_formatter) ----------


class TestFormatErrorDiff:
    def test_same_reports(self):
        report = {"failure_type": "precondition_violated", "counterexample": {"a": 0}}
        diff = format_error_diff(report, report)
        assert "UNCHANGED" in diff
        # Every line should say UNCHANGED, none should say ": CHANGED"
        for line in diff.splitlines():
            if ":" in line:
                assert ": CHANGED" not in line

    def test_different_failure_type(self):
        prev = {"failure_type": "precondition_violated"}
        curr = {"failure_type": "postcondition_violated"}
        diff = format_error_diff(prev, curr)
        assert "CHANGED" in diff
        assert "precondition_violated" in diff
        assert "postcondition_violated" in diff

    def test_counterexample_change(self):
        prev = {"failure_type": "x", "counterexample": {"a": 0, "b": 0}}
        curr = {"failure_type": "x", "counterexample": {"a": 5, "b": -1}}
        diff = format_error_diff(prev, curr)
        assert "counterexample: CHANGED" in diff

    def test_suggestion_change(self):
        prev = {"failure_type": "x", "suggestion": "add requires"}
        curr = {"failure_type": "x", "suggestion": "widen type"}
        diff = format_error_diff(prev, curr)
        assert "suggestion: CHANGED" in diff
        assert "widen type" in diff

    def test_violation_type_included_when_present(self):
        prev = {"failure_type": "x", "violation_type": "effect_mismatch"}
        curr = {"failure_type": "x", "violation_type": "effect_propagation"}
        diff = format_error_diff(prev, curr)
        assert "violation_type: CHANGED" in diff

    def test_no_violation_type_when_absent(self):
        prev = {"failure_type": "x"}
        curr = {"failure_type": "x"}
        diff = format_error_diff(prev, curr)
        assert "violation_type" not in diff
