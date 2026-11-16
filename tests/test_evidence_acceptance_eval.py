"""Route tests for ``evidence-acceptance-eval``: folding a declared
Core acceptance descriptor into ``mumei.core-acceptance-evaluation/v1``.

Representation-level only — anonymous Core descriptors bind no attempt,
so `accepted` credits nothing to a selected output."""

import json
from pathlib import Path

import pytest

from agent.core_evidence import evaluate_core_acceptance
from agent.evidence_acceptance_eval import (
    build_eval_parser,
    main_eval,
)


def _descriptor(accepted: bool = True, **overrides) -> dict:
    value = {
        "schema_version": "mumei.source-evidence-acceptance/v1",
        "acceptance": "evaluated",
        "accepted": accepted,
        "scope": "saved_source_record_and_fresh_same_profile_recheck",
        "checks_performed": ["representation_check", "fresh_source_recheck"],
        "checks_not_performed": ["producer_authenticity"],
    }
    value.update(overrides)
    return value


def _write(path: Path, value) -> Path:
    path.write_text(json.dumps(value) if not isinstance(value, str) else value)
    return path


def test_known_descriptors_fold_to_accepted_evaluation(tmp_path, capsys):
    for schema in (
        "mumei.source-evidence-acceptance/v1",
        "mumei.native-evidence-acceptance/v1",
    ):
        evaluation = evaluate_core_acceptance(
            _descriptor(schema_version=schema)
        )
        assert evaluation["schema_version"] == (
            "mumei.core-acceptance-evaluation/v1"
        )
        assert evaluation["descriptor_match"] is True
        assert evaluation["accepted"] is True
        assert "attempt_binding" in evaluation["checks_not_performed"]

    descriptor = _write(tmp_path / "desc.json", _descriptor())
    parser = __import__("argparse").ArgumentParser()
    build_eval_parser(parser)
    exit_code = main_eval(
        parser.parse_args(["--descriptor", str(descriptor)])
    )
    assert exit_code == 0
    emitted = json.loads(capsys.readouterr().out)
    assert emitted["accepted"] is True


def test_unmatched_or_unaccepted_descriptors_never_credit_acceptance(
    tmp_path, capsys
):
    # A well-formed descriptor that itself declares non-acceptance is a
    # genuine member of the family: it matches, but credits nothing.
    declined = evaluate_core_acceptance(_descriptor(accepted=False))
    assert declined["descriptor_match"] is True
    assert declined["accepted"] is False

    cases = [
        _descriptor(schema_version="mumei.verification-evidence/v1"),
        _descriptor(schema_version="mumei.probe-acceptance/v1"),
        _descriptor(acceptance="not_evaluated"),
        _descriptor(accepted="true"),                     # not a bool
        _descriptor(scope=""),
        _descriptor(scope=123),
        _descriptor(checks_performed="fresh_source_recheck"),
        _descriptor(checks_not_performed=[1, 2]),
        {**_descriptor(), "extra": None},                 # open shape
        {k: v for k, v in _descriptor().items() if k != "scope"},
    ]
    for value in cases:
        evaluation = evaluate_core_acceptance(value)
        assert evaluation["descriptor_match"] is False
        assert evaluation["accepted"] is False

    # The route never raises on a well-formed-but-foreign document; it
    # emits match=False, not an acceptance.
    foreign = _write(
        tmp_path / "foreign.json",
        _descriptor(schema_version="mumei.probe-acceptance/v1"),
    )
    parser = __import__("argparse").ArgumentParser()
    build_eval_parser(parser)
    assert main_eval(
        parser.parse_args(["--descriptor", str(foreign)])
    ) == 0
    assert json.loads(capsys.readouterr().out)["accepted"] is False


def test_malformed_and_missing_inputs_fail_statically(tmp_path, capsys):
    parser = __import__("argparse").ArgumentParser()
    build_eval_parser(parser)
    for body in ["not json", "[]", "1"]:
        bad = _write(tmp_path / "bad.json", body)
        assert main_eval(parser.parse_args(["--descriptor", str(bad)])) == 1
        capsys.readouterr()  # drain stderr without asserting its text
    assert main_eval(
        parser.parse_args(["--descriptor", str(tmp_path / "missing.json")])
    ) == 1
    # --output may not overwrite the declared input.
    descriptor = _write(tmp_path / "desc.json", _descriptor())
    assert main_eval(
        parser.parse_args(
            ["--descriptor", str(descriptor), "--output", str(descriptor)]
        )
    ) == 1


def test_non_dict_descriptor_input_is_a_static_error():
    with pytest.raises(ValueError):
        evaluate_core_acceptance(["not", "a", "dict"])

def test_unhashable_field_types_never_raise(tmp_path):
    # schema_version/acceptance as list or dict must fold to match=False,
    # not crash on `in frozenset`.
    for weird in (
        _descriptor(schema_version=["mumei.source-evidence-acceptance/v1"]),
        _descriptor(schema_version={"v": 1}),
        _descriptor(acceptance=["evaluated"]),
        _descriptor(acceptance={"v": "evaluated"}),
    ):
        evaluation = evaluate_core_acceptance(weird)
        assert evaluation["descriptor_match"] is False
        assert evaluation["accepted"] is False


def test_optional_evidence_fingerprint_field(tmp_path):
    # Core acceptance descriptors may carry evidence_fingerprint — the
    # SHA-256 hex of the accepted record's bytes. A valid one keeps the
    # match; a malformed one breaks it like a foreign field.
    good = evaluate_core_acceptance(
        _descriptor(evidence_fingerprint="a" * 64)
    )
    assert good["descriptor_match"] is True
    assert good["accepted"] is True

    for bad in ("A" * 64, "abc", 123, None, ["a" * 64]):
        evaluation = evaluate_core_acceptance(
            _descriptor(evidence_fingerprint=bad)
        )
        assert evaluation["descriptor_match"] is False
        assert evaluation["accepted"] is False

    # Unknown extra fields still break the match.
    foreign = evaluate_core_acceptance(
        _descriptor(evidence_fingerprint="b" * 64, foreign_field=1)
    )
    assert foreign["descriptor_match"] is False


def test_expected_fingerprint_binds_descriptor_to_attempt(tmp_path, capsys):
    fingerprint = "c" * 64
    descriptor = _descriptor(evidence_fingerprint=fingerprint)

    # Equal pins bind the descriptor to the declared attempt record and
    # attempt_binding leaves checks_not_performed.
    bound = evaluate_core_acceptance(descriptor, fingerprint)
    assert bound["descriptor_match"] is True
    assert bound["accepted"] is True
    assert bound["attempt_bound"] is True
    assert "attempt_binding" not in bound["checks_not_performed"]

    # A different pin reports attempt_bound=False — an observation, not
    # an error (the descriptor may honestly describe another record).
    other = evaluate_core_acceptance(descriptor, "d" * 64)
    assert other["descriptor_match"] is True
    assert other["attempt_bound"] is False

    # A matched descriptor that carries no fingerprint cannot bind.
    unpinned = evaluate_core_acceptance(_descriptor(), fingerprint)
    assert unpinned["descriptor_match"] is True
    assert unpinned["attempt_bound"] is False

    # A non-matching descriptor can never bind.
    foreign = evaluate_core_acceptance(
        _descriptor(schema_version="mumei.probe-acceptance/v1"), fingerprint
    )
    assert foreign["descriptor_match"] is False
    assert foreign["attempt_bound"] is False

    # Without an expected fingerprint the key is absent and the check
    # stays honestly unperformed.
    plain = evaluate_core_acceptance(descriptor)
    assert "attempt_bound" not in plain
    assert "attempt_binding" in plain["checks_not_performed"]

    # A malformed expected fingerprint is a static request error.
    for bad in ("ABC", "a" * 63, 123, ["a" * 64]):
        with pytest.raises(ValueError):
            evaluate_core_acceptance(descriptor, bad)

    # The route forwards --expected-fingerprint.
    path = _write(tmp_path / "desc.json", descriptor)
    parser = __import__("argparse").ArgumentParser()
    build_eval_parser(parser)
    exit_code = main_eval(
        parser.parse_args(
            ["--descriptor", str(path), "--expected-fingerprint", fingerprint]
        )
    )
    assert exit_code == 0
    emitted = json.loads(capsys.readouterr().out)
    assert emitted["attempt_bound"] is True
    assert "attempt_binding" not in emitted["checks_not_performed"]
