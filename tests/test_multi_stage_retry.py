"""Integration tests for multi-stage retry with re-diagnosis and error diffs."""
from unittest.mock import MagicMock, patch, call

from agent.strategies.multi_stage_strategy import (
    get_fix_multi_stage,
    _diagnose,
    _build_retry_context,
)
from agent.strategies.retry_history import RetryAttempt, RetryHistory


def _make_response(text: str) -> MagicMock:
    """Create a mock completion response."""
    message = MagicMock()
    message.content = text
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _diagnosis_json(root_cause: str, approach: str, section: str = "requires") -> str:
    import json

    return json.dumps(
        {
            "root_cause": root_cause,
            "fix_approach": approach,
            "target_section": section,
        }
    )


# ---------- Re-diagnosis on retry ----------


class TestReDiagnosisOnRetry:
    """Verify that the multi-stage strategy re-runs diagnosis on each iteration."""

    def test_diagnoses_called_on_each_retry(self):
        """After a failed validation, a new diagnosis should be requested."""
        client = MagicMock()
        client.chat.completions.create.side_effect = [
            # Iteration 0: diagnosis
            _make_response(
                _diagnosis_json("div zero", "add requires guard")
            ),
            # Iteration 0: fix
            _make_response("```mumei\natom fix_v1() body: 1;\n```"),
            # Iteration 1: RE-diagnosis (new error context)
            _make_response(
                _diagnosis_json("postcondition fail", "adjust ensures")
            ),
            # Iteration 1: fix
            _make_response("```mumei\natom fix_v2() body: 2;\n```"),
            # Iteration 2: RE-diagnosis
            _make_response(
                _diagnosis_json("body logic error", "rewrite body")
            ),
            # Iteration 2: fix
            _make_response("```mumei\natom fix_v3() body: 3;\n```"),
        ]

        mumei_client = MagicMock()
        # All validations fail
        mumei_client.verify.return_value = {
            "success": False,
            "report": {"failure_type": "postcondition_violated"},
            "stdout": "err",
            "stderr": "",
        }

        result = get_fix_multi_stage(
            client, "m", "src", "err", {"failure_type": "precondition_violated"},
            mumei_client, "test.mm",
        )

        # 3 iterations * 2 LLM calls each (diagnose + fix) = 6
        assert client.chat.completions.create.call_count == 6
        assert result == "atom fix_v3() body: 3;"

    def test_successful_validation_stops_early(self):
        """If validation passes on first try, no re-diagnosis needed."""
        client = MagicMock()
        client.chat.completions.create.side_effect = [
            _make_response(_diagnosis_json("x", "y")),
            _make_response("```mumei\natom ok() body: 1;\n```"),
        ]

        mumei_client = MagicMock()
        mumei_client.verify.return_value = {
            "success": True,
            "report": {"status": "ok"},
            "stdout": "",
            "stderr": "",
        }

        result = get_fix_multi_stage(
            client, "m", "src", "err", {"failure_type": "x"},
            mumei_client, "test.mm",
        )
        assert result == "atom ok() body: 1;"
        assert client.chat.completions.create.call_count == 2


# ---------- Error diff in prompts ----------


class TestErrorDiffInPrompts:
    """Verify that error diff context is included in fix prompts after first attempt."""

    def test_no_retry_context_on_first_attempt(self):
        """First iteration should not include retry context."""
        client = MagicMock()
        client.chat.completions.create.side_effect = [
            _make_response(_diagnosis_json("x", "y")),
            _make_response("```mumei\natom ok() body: 1;\n```"),
        ]

        mumei_client = MagicMock()
        mumei_client.verify.return_value = {
            "success": True,
            "report": {},
            "stdout": "",
            "stderr": "",
        }

        get_fix_multi_stage(
            client, "m", "src", "err", {},
            mumei_client, "test.mm",
        )

        # The fix prompt (second call) should NOT contain retry sections
        fix_call = client.chat.completions.create.call_args_list[1]
        fix_prompt = fix_call.kwargs["messages"][1]["content"]
        assert "Previous Fix Attempts" not in fix_prompt

    def test_retry_context_on_second_attempt(self):
        """Second iteration should include retry history and error diff."""
        client = MagicMock()
        client.chat.completions.create.side_effect = [
            # Iter 0: diagnose
            _make_response(_diagnosis_json("cause1", "approach1")),
            # Iter 0: fix
            _make_response("```mumei\natom v1() body: 1;\n```"),
            # Iter 1: re-diagnose
            _make_response(_diagnosis_json("cause2", "approach2")),
            # Iter 1: fix
            _make_response("```mumei\natom v2() body: 2;\n```"),
        ]

        mumei_client = MagicMock()
        mumei_client.verify.side_effect = [
            # First validation fails
            {
                "success": False,
                "report": {
                    "failure_type": "precondition_violated",
                    "counterexample": {"a": 0},
                },
                "stdout": "fail1",
                "stderr": "",
            },
            # Second validation passes
            {
                "success": True,
                "report": {"status": "ok"},
                "stdout": "",
                "stderr": "",
            },
        ]

        get_fix_multi_stage(
            client, "m", "src", "err",
            {"failure_type": "precondition_violated", "counterexample": {"a": 0}},
            mumei_client, "test.mm",
        )

        # The fix prompt on the second iteration (4th LLM call) should
        # contain retry context
        fix_call = client.chat.completions.create.call_args_list[3]
        fix_prompt = fix_call.kwargs["messages"][1]["content"]
        assert "Previous Fix Attempts" in fix_prompt
        assert "Attempt 1" in fix_prompt


# ---------- Approach-switching ----------


class TestApproachSwitching:
    """Verify approach-switch instruction when same error repeats."""

    def test_approach_switch_on_repeated_error(self):
        """When the same error repeats, the diagnosis prompt should include
        the approach-switch instruction."""
        client = MagicMock()
        client.chat.completions.create.side_effect = [
            # Iter 0: diagnose
            _make_response(_diagnosis_json("cause", "approach_a")),
            # Iter 0: fix
            _make_response("```mumei\natom v1() body: 1;\n```"),
            # Iter 1: re-diagnose
            _make_response(_diagnosis_json("cause", "approach_b")),
            # Iter 1: fix
            _make_response("```mumei\natom v2() body: 2;\n```"),
            # Iter 2: re-diagnose (same error repeated 2x -> approach switch)
            _make_response(_diagnosis_json("cause", "approach_c")),
            # Iter 2: fix
            _make_response("```mumei\natom v3() body: 3;\n```"),
        ]

        same_error = {
            "failure_type": "precondition_violated",
            "counterexample": {"a": 0},
        }
        mumei_client = MagicMock()
        mumei_client.verify.return_value = {
            "success": False,
            "report": same_error,
            "stdout": "same err",
            "stderr": "",
        }

        get_fix_multi_stage(
            client, "m", "src", "err", same_error,
            mumei_client, "test.mm",
        )

        # On iteration 2, the diagnosis prompt (5th LLM call, index 4) should
        # contain the approach-switch instruction because the same error
        # repeated in attempts 1 and 2.
        diag_call_iter2 = client.chat.completions.create.call_args_list[4]
        diag_prompt = diag_call_iter2.kwargs["messages"][1]["content"]
        assert "MUST try a fundamentally different fix strategy" in diag_prompt

    def test_no_approach_switch_on_different_errors(self):
        """When errors change between iterations, no approach-switch."""
        client = MagicMock()
        client.chat.completions.create.side_effect = [
            _make_response(_diagnosis_json("c1", "a1")),
            _make_response("```mumei\natom v1() body: 1;\n```"),
            _make_response(_diagnosis_json("c2", "a2")),
            _make_response("```mumei\natom v2() body: 2;\n```"),
        ]

        mumei_client = MagicMock()
        mumei_client.verify.side_effect = [
            {
                "success": False,
                "report": {
                    "failure_type": "postcondition_violated",
                    "counterexample": {"x": 1},
                },
                "stdout": "err",
                "stderr": "",
            },
            {"success": True, "report": {}, "stdout": "", "stderr": ""},
        ]

        get_fix_multi_stage(
            client, "m", "src", "err",
            {"failure_type": "precondition_violated", "counterexample": {"a": 0}},
            mumei_client, "test.mm",
        )

        # Diagnosis on second iteration should NOT have approach switch
        diag_call_iter1 = client.chat.completions.create.call_args_list[2]
        diag_prompt = diag_call_iter1.kwargs["messages"][1]["content"]
        assert "fundamentally different" not in diag_prompt


# ---------- Retry history threading ----------


class TestRetryHistoryThreading:
    """Verify that an external RetryHistory is accepted and used."""

    def test_external_history_is_used(self):
        """Pre-populated history should appear in the fix prompt."""
        history = RetryHistory()
        history.add(
            RetryAttempt(
                attempt_number=1,
                source_code="old_src",
                error_log="old_err",
                report_data={"failure_type": "precondition_violated"},
                diagnosis={
                    "root_cause": "old_cause",
                    "fix_approach": "old_approach",
                    "target_section": "requires",
                },
            )
        )

        client = MagicMock()
        client.chat.completions.create.side_effect = [
            _make_response(_diagnosis_json("new_cause", "new_approach")),
            _make_response("```mumei\natom ok() body: 1;\n```"),
        ]

        mumei_client = MagicMock()
        mumei_client.verify.return_value = {
            "success": True,
            "report": {},
            "stdout": "",
            "stderr": "",
        }

        get_fix_multi_stage(
            client, "m", "src", "err", {"failure_type": "x"},
            mumei_client, "test.mm",
            retry_history=history,
        )

        # Fix prompt should reference the pre-existing attempt
        fix_call = client.chat.completions.create.call_args_list[1]
        fix_prompt = fix_call.kwargs["messages"][1]["content"]
        assert "old_cause" in fix_prompt
        assert "Previous Fix Attempts" in fix_prompt


# ---------- _build_retry_context ----------


class TestBuildRetryContext:
    def test_empty_history(self):
        assert _build_retry_context(RetryHistory()) == ""

    def test_with_attempts(self):
        h = RetryHistory()
        h.add(
            RetryAttempt(
                attempt_number=1,
                source_code="s",
                error_log="e",
                report_data={"failure_type": "x"},
                diagnosis={
                    "root_cause": "r",
                    "fix_approach": "f",
                    "target_section": "t",
                },
            )
        )
        ctx = _build_retry_context(h)
        assert "Previous Fix Attempts" in ctx
        assert "Attempt 1" in ctx
