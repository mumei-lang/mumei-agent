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
