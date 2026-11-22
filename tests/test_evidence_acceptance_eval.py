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
    run_eval,
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


_NATIVE = "mumei.native-evidence-acceptance/v1"
_OBSERVATION_PERFORMED = ["runtime_observation_semantics", "os_exit_status_observation"]


def _observation_invocation() -> dict:
    # Shape `observation_invocation_envelope()` emits on the
    # accept-observations route.
    return {
        "argv": [],
        "stdin": "closed",
        "timeout_ms": 30000,
        "channel_cap_bytes": 65536,
        "environment": "empty",
        "working_directory": "executable_directory",
    }


def _observation_host() -> dict:
    return {"os": "linux", "arch": "x86_64", "family": "unix"}


def test_native_observation_route_extra_fields(tmp_path):
    # The accept-observations descriptor pins invocation/host and may
    # carry pin_envelope — only when runtime_observation_semantics was
    # performed. Both extras fold to a match.
    descriptor = _descriptor(
        schema_version=_NATIVE,
        checks_performed=_OBSERVATION_PERFORMED,
        invocation=_observation_invocation(),
        host=_observation_host(),
        pin_envelope="recorded",
    )
    evaluation = evaluate_core_acceptance(descriptor)
    assert evaluation["descriptor_match"] is True
    assert evaluation["accepted"] is True

    # pin_envelope stays optional; invocation and host still fold.
    evaluation = evaluate_core_acceptance(
        _descriptor(
            schema_version=_NATIVE,
            checks_performed=_OBSERVATION_PERFORMED,
            invocation=_observation_invocation(),
            host=_observation_host(),
        )
    )
    assert evaluation["descriptor_match"] is True


def test_native_observation_extras_require_performed_check(tmp_path):
    # Core only emits the observation pins when it performed
    # runtime_observation_semantics — pins without that check do not
    # fold, and they never fold on the source-schema route.
    for key, value in (
        ("invocation", _observation_invocation()),
        ("host", _observation_host()),
        ("pin_envelope", "unrecorded"),
    ):
        evaluation = evaluate_core_acceptance(
            _descriptor(
                schema_version=_NATIVE,
                checks_performed=["fresh_source_recheck"],
                **{key: value},
            )
        )
        assert evaluation["descriptor_match"] is False
        evaluation = evaluate_core_acceptance(
            _descriptor(
                checks_performed=_OBSERVATION_PERFORMED,
                **{key: value},
            )
        )
        assert evaluation["descriptor_match"] is False


def test_native_object_route_extra_fields(tmp_path):
    # The object-machine-TV acceptance descriptor pins the compared
    # artifacts and the per-function outcome.
    evaluation = evaluate_core_acceptance(
        _descriptor(
            schema_version=_NATIVE,
            build_id="e" * 64,
            llvm_sha256="f" * 64,
            object_sha256="1" * 64,
            register_convention_assumed="sysv_amd64",
            input_domain="loops_unrolled_refined_signatures",
            functions={"main": {"outcome": "equivalent"}},
        )
    )
    assert evaluation["descriptor_match"] is True
    assert evaluation["accepted"] is True


def test_native_extra_fields_validate_shapes(tmp_path):
    # An extra field with a malformed value breaks the match exactly
    # like a foreign field — the whitelist is not a free pass.
    bad_cases = [
        {"invocation": "closed"},
        {"invocation": {**_observation_invocation(), "argv": [1]}},
        {"invocation": {**_observation_invocation(), "timeout_ms": -1}},
        {
            "invocation": {
                **_observation_invocation(),
                "surprise": True,
            }
        },
        {"host": {"os": "linux"}},
        {"host": {**_observation_host(), "arch": 64}},
        {"pin_envelope": "tampered"},
        {"pin_envelope": 3},
        {"build_id": ""},
        {"llvm_sha256": "zz" * 32},
        {"object_sha256": "A" * 64},
        {"register_convention_assumed": ["sysv_amd64"]},
        {"input_domain": 7},
        {"functions": ["main"]},
        {"foreign_field": {}},
    ]
    for extra in bad_cases:
        evaluation = evaluate_core_acceptance(
            _descriptor(
                schema_version=_NATIVE,
                checks_performed=_OBSERVATION_PERFORMED,
                **extra,
            )
        )
        assert evaluation["descriptor_match"] is False, extra


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


def _conjunctive_descriptor(verdict: str = "accepted", **overrides) -> dict:
    """The closed shape Core `evidence accept --requirement-list` emits."""
    value = {
        "schema_version": "mumei.evidence-requirement-list-acceptance/v1",
        "acceptance": "evaluated",
        "verdict": verdict,
        "requirement_schema_version": "mumei.evidence-requirement-list/v1",
        "requirement_list_fingerprint": "e" * 64,
        "evidence_schema_version": "mumei.verification-evidence/v1",
        "evidence_fingerprint": "f" * 64,
        "consistent": True,
        "conflict_count": 0,
        "conflicts": [],
        "requirements_evaluated": 1,
        "records_evaluated": 1,
        "requirements": [
            {
                "index": 0,
                "requirement_fingerprint": "0" * 64,
                "verdict": "accepted",
                "records": [
                    {
                        "index": 0,
                        "verdict": "accepted",
                        "checks": [{"name": "c", "outcome": "passed"}],
                    }
                ],
            }
        ],
        "checks_performed": ["conjunctive_requirement_fold"],
        "checks_not_performed": ["claim_truth"],
    }
    value.update(overrides)
    return value


def _conjunctive_list_descriptor(**overrides) -> dict:
    value = _conjunctive_descriptor(
        evidence_schema_version="mumei.verification-evidence-list/v1",
        list_fingerprint="1" * 64,
    )
    del value["evidence_fingerprint"]
    value.update(overrides)
    return value


def test_conjunctive_descriptor_folds_to_accepted_evaluation(
    tmp_path, capsys
):
    evaluation = evaluate_core_acceptance(_conjunctive_descriptor())
    assert evaluation["schema_version"] == (
        "mumei.core-acceptance-evaluation/v1"
    )
    assert evaluation["descriptor_match"] is True
    assert evaluation["accepted"] is True
    assert "attempt_binding" in evaluation["checks_not_performed"]

    # The list-pinned variant is an equally valid family member.
    listed = evaluate_core_acceptance(_conjunctive_list_descriptor())
    assert listed["descriptor_match"] is True
    assert listed["accepted"] is True

    # The route accepts the conjunctive descriptor end to end.
    descriptor = _write(
        tmp_path / "conj.json", _conjunctive_descriptor()
    )
    parser = __import__("argparse").ArgumentParser()
    build_eval_parser(parser)
    assert (
        main_eval(parser.parse_args(["--descriptor", str(descriptor)]))
        == 0
    )
    assert json.loads(capsys.readouterr().out)["accepted"] is True


def test_conjunctive_non_accepted_verdicts_credit_nothing():
    for verdict in ("rejected", "inconclusive"):
        evaluation = evaluate_core_acceptance(
            _conjunctive_descriptor(verdict=verdict)
        )
        assert evaluation["descriptor_match"] is True
        assert evaluation["accepted"] is False


def test_conjunctive_closed_shape_rejects_foreign_documents():
    cases = [
        _conjunctive_descriptor(verdict="unknown"),
        _conjunctive_descriptor(verdict=True),
        _conjunctive_descriptor(acceptance="not_evaluated"),
        _conjunctive_descriptor(
            requirement_schema_version="mumei.probe/v1"
        ),
        _conjunctive_descriptor(requirement_list_fingerprint="abc"),
        _conjunctive_descriptor(evidence_schema_version="mumei.probe/v1"),
        _conjunctive_descriptor(evidence_fingerprint="F" * 64),
        _conjunctive_descriptor(consistent="yes"),
        _conjunctive_descriptor(conflict_count=-1),
        _conjunctive_descriptor(conflict_count=True),
        _conjunctive_descriptor(conflicts={"field": "x"}),
        _conjunctive_descriptor(requirements_evaluated="1"),
        _conjunctive_descriptor(records_evaluated=None),
        _conjunctive_descriptor(requirements={}),
        _conjunctive_descriptor(checks_performed="fold"),
        _conjunctive_descriptor(checks_not_performed=[1]),
        {**_conjunctive_descriptor(), "extra": 1},
        {
            k: v
            for k, v in _conjunctive_descriptor().items()
            if k != "verdict"
        },
        # Both pins at once is ambiguous — never a member.
        _conjunctive_descriptor(list_fingerprint="1" * 64),
        # Neither pin names the evaluated evidence.
        {
            k: v
            for k, v in _conjunctive_descriptor().items()
            if k != "evidence_fingerprint"
        },
        # Pin/schema mismatches: list pin on record schema and the
        # converse are foreign, not a different opinion.
        _conjunctive_descriptor(
            evidence_schema_version="mumei.verification-evidence-list/v1"
        ),
        _conjunctive_list_descriptor(
            evidence_schema_version="mumei.verification-evidence/v1"
        ),
    ]
    for value in cases:
        evaluation = evaluate_core_acceptance(value)
        assert evaluation["descriptor_match"] is False, value
        assert evaluation["accepted"] is False


def test_conjunctive_nested_shapes_are_closed_too():
    def with_requirement(requirement):
        return _conjunctive_descriptor(requirements=[requirement])

    requirement = _conjunctive_descriptor()["requirements"][0]
    record = requirement["records"][0]

    bad_requirements = [
        {**requirement, "extra": 1},
        {k: v for k, v in requirement.items() if k != "verdict"},
        {**requirement, "index": -1},
        {**requirement, "index": True},
        {**requirement, "requirement_fingerprint": "xyz"},
        {**requirement, "verdict": "maybe"},
        {**requirement, "verdict": ["accepted"]},
        {**requirement, "records": "not-a-list"},
        {**requirement, "records": [{**record, "extra": 0}]},
        {
            **requirement,
            "records": [
                {k: v for k, v in record.items() if k != "checks"}
            ],
        },
        {**requirement, "records": [{**record, "index": "0"}]},
        {**requirement, "records": [{**record, "verdict": "ok"}]},
        {**requirement, "records": [{**record, "checks": "n"}]},
        {
            **requirement,
            "records": [
                {**record, "checks": [{"name": "c"}]}
            ],
        },
        {
            **requirement,
            "records": [
                {
                    **record,
                    "checks": [{"name": 1, "outcome": "passed"}],
                }
            ],
        },
        {
            **requirement,
            "records": [
                {
                    **record,
                    "checks": [
                        {"name": "c", "outcome": "passed", "x": 0}
                    ],
                }
            ],
        },
    ]
    for value in bad_requirements:
        evaluation = evaluate_core_acceptance(with_requirement(value))
        assert evaluation["descriptor_match"] is False, value
        assert evaluation["accepted"] is False

    # conflicts entries are the same closed {index_a, index_b, field}
    # shape Core's consistency report emits.
    for conflicts in (
        [{"index_a": 0, "index_b": 1, "field": "subject.kind"}],
        [{"index_a": 0, "index_b": 1, "field": "f", "extra": 0}],
        [{"index_a": -1, "index_b": 1, "field": "f"}],
        [{"index_a": "0", "index_b": 1, "field": "f"}],
        [{"index_a": 0, "index_b": 1, "field": 7}],
        ["a-string-conflict"],
    ):
        value = _conjunctive_descriptor(conflicts=conflicts)
        matched = evaluate_core_acceptance(value)["descriptor_match"]
        assert matched is (len(conflicts[0]) == 3 and
            type(conflicts[0]["index_a"]) is int
            and conflicts[0]["index_a"] >= 0
            and type(conflicts[0]["field"]) is str), conflicts


def test_conjunctive_attempt_binding_uses_evidence_fingerprint(
    tmp_path, capsys
):
    fingerprint = "f" * 64
    bound = evaluate_core_acceptance(
        _conjunctive_descriptor(), fingerprint
    )
    assert bound["descriptor_match"] is True
    assert bound["attempt_bound"] is True
    assert "attempt_binding" not in bound["checks_not_performed"]

    other = evaluate_core_acceptance(
        _conjunctive_descriptor(), "d" * 64
    )
    assert other["attempt_bound"] is False

    # A list-pinned descriptor can never bind a single-record attempt —
    # honest false, not an error.
    listed = evaluate_core_acceptance(
        _conjunctive_list_descriptor(), fingerprint
    )
    assert listed["descriptor_match"] is True
    assert listed["attempt_bound"] is False

    # The route forwards --expected-fingerprint on the conjunctive shape.
    path = _write(tmp_path / "conj.json", _conjunctive_descriptor())
    parser = __import__("argparse").ArgumentParser()
    build_eval_parser(parser)
    assert (
        main_eval(
            parser.parse_args(
                [
                    "--descriptor",
                    str(path),
                    "--expected-fingerprint",
                    fingerprint,
                ]
            )
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["attempt_bound"] is True


def test_real_core_conjunctive_descriptors_fold(tmp_path):
    # Golden descriptors emitted by real Core
    # `evidence accept --requirement-list --json` (record pin) and
    # `evidence accept-list --requirement-list --json` (list pin) —
    # regenerate with a built mumei when the descriptor shape changes.
    fixtures = Path(__file__).parent / "fixtures"
    for name, pin in (
        ("evidence_requirement_list_acceptance.json", "evidence_fingerprint"),
        ("evidence_requirement_list_acceptance_list_pin.json", "list_fingerprint"),
    ):
        descriptor = json.loads((fixtures / name).read_text())
        evaluation = evaluate_core_acceptance(descriptor)
        assert evaluation["descriptor_match"] is True, name
        assert evaluation["accepted"] is True, name
        assert pin in descriptor

        bound = evaluate_core_acceptance(
            descriptor, descriptor.get("evidence_fingerprint") or "0" * 64
        )
        assert bound["attempt_bound"] is (pin == "evidence_fingerprint")

        # The route accepts the real descriptor end to end.
        evaluation = run_eval(
            __import__("argparse").Namespace(
                descriptor=str(fixtures / name),
                expected_fingerprint=None,
                output=None,
            )
        )
        assert evaluation["descriptor_match"] is True


def _evidence_acceptance_descriptor(verdict: str = "accepted", **overrides):
    """The shape Core `evidence accept --requirement` emits."""
    value = {
        "schema_version": "mumei.evidence-acceptance/v1",
        "acceptance": "evaluated",
        "verdict": verdict,
        "requirement_schema_version": "mumei.evidence-requirement/v1",
        "requirement_fingerprint": "a" * 64,
        "evidence_schema_version": "mumei.verification-evidence/v1",
        "evidence_fingerprint": "b" * 64,
        "checks": [{"name": "subject_pin", "outcome": "passed"}],
        "checks_performed": ["requirement_normalization"],
        "checks_not_performed": ["claim_truth"],
    }
    value.update(overrides)
    return value


def _evidence_list_acceptance_descriptor(
    verdict: str = "accepted", **overrides
):
    """The shape Core `evidence accept-list --requirement` emits."""
    value = {
        "schema_version": "mumei.evidence-list-acceptance/v1",
        "acceptance": "evaluated",
        "verdict": verdict,
        "requirement_schema_version": "mumei.evidence-requirement/v1",
        "requirement_fingerprint": "a" * 64,
        "evidence_schema_version": "mumei.verification-evidence-list/v1",
        "list_fingerprint": "2" * 64,
        "consistent": True,
        "conflict_count": 0,
        "conflicts": [],
        "records_evaluated": 1,
        "records": [
            {
                "index": 0,
                "verdict": "accepted",
                "checks": [{"name": "subject_pin", "outcome": "passed"}],
            }
        ],
        "checks_performed": ["requirement_normalization"],
        "checks_not_performed": ["claim_truth"],
    }
    value.update(overrides)
    return value


def test_evidence_acceptance_descriptor_folds(tmp_path, capsys):
    evaluation = evaluate_core_acceptance(
        _evidence_acceptance_descriptor()
    )
    assert evaluation["descriptor_match"] is True
    assert evaluation["accepted"] is True

    for verdict in ("rejected", "inconclusive"):
        evaluation = evaluate_core_acceptance(
            _evidence_acceptance_descriptor(verdict=verdict)
        )
        assert evaluation["descriptor_match"] is True
        assert evaluation["accepted"] is False

    # Closed shape: foreign or missing fields never match.
    cases = [
        _evidence_acceptance_descriptor(verdict="maybe"),
        _evidence_acceptance_descriptor(verdict=["accepted"]),
        _evidence_acceptance_descriptor(acceptance="not_evaluated"),
        _evidence_acceptance_descriptor(
            requirement_schema_version="mumei.probe/v1"
        ),
        _evidence_acceptance_descriptor(requirement_fingerprint="x"),
        _evidence_acceptance_descriptor(
            evidence_schema_version="mumei.probe/v1"
        ),
        _evidence_acceptance_descriptor(evidence_fingerprint="B" * 64),
        _evidence_acceptance_descriptor(checks="subject_pin"),
        _evidence_acceptance_descriptor(
            checks=[{"name": "c", "outcome": "passed", "x": 0}]
        ),
        _evidence_acceptance_descriptor(checks=[{"name": 1, "outcome": "p"}]),
        _evidence_acceptance_descriptor(checks_performed="norm"),
        {**_evidence_acceptance_descriptor(), "extra": None},
        {
            k: v
            for k, v in _evidence_acceptance_descriptor().items()
            if k != "checks"
        },
        # The record pin may not be swapped for a list pin.
        _evidence_acceptance_descriptor(list_fingerprint="2" * 64),
    ]
    for value in cases:
        evaluation = evaluate_core_acceptance(value)
        assert evaluation["descriptor_match"] is False, value
        assert evaluation["accepted"] is False


def test_evidence_list_acceptance_descriptor_folds(tmp_path, capsys):
    evaluation = evaluate_core_acceptance(
        _evidence_list_acceptance_descriptor()
    )
    assert evaluation["descriptor_match"] is True
    assert evaluation["accepted"] is True

    for verdict in ("rejected", "inconclusive"):
        evaluation = evaluate_core_acceptance(
            _evidence_list_acceptance_descriptor(verdict=verdict)
        )
        assert evaluation["descriptor_match"] is True
        assert evaluation["accepted"] is False

    record = _evidence_list_acceptance_descriptor()["records"][0]
    cases = [
        _evidence_list_acceptance_descriptor(
            evidence_schema_version="mumei.verification-evidence/v1"
        ),
        _evidence_list_acceptance_descriptor(list_fingerprint="x"),
        _evidence_list_acceptance_descriptor(
            evidence_fingerprint="b" * 64
        ),
        _evidence_list_acceptance_descriptor(consistent="yes"),
        _evidence_list_acceptance_descriptor(conflict_count=-1),
        _evidence_list_acceptance_descriptor(conflicts={"a": 1}),
        _evidence_list_acceptance_descriptor(
            conflicts=[{"index_a": 0, "index_b": 1}]
        ),
        _evidence_list_acceptance_descriptor(records_evaluated="1"),
        _evidence_list_acceptance_descriptor(records={}),
        _evidence_list_acceptance_descriptor(
            records=[{**record, "extra": 0}]
        ),
        _evidence_list_acceptance_descriptor(
            records=[{k: v for k, v in record.items() if k != "verdict"}]
        ),
        _evidence_list_acceptance_descriptor(
            records=[{**record, "index": "0"}]
        ),
        _evidence_list_acceptance_descriptor(
            records=[{**record, "verdict": "ok"}]
        ),
        _evidence_list_acceptance_descriptor(
            records=[{**record, "checks": [{"name": "c"}]}]
        ),
        {**_evidence_list_acceptance_descriptor(), "extra": 1},
        {
            k: v
            for k, v in _evidence_list_acceptance_descriptor().items()
            if k != "list_fingerprint"
        },
    ]
    for value in cases:
        evaluation = evaluate_core_acceptance(value)
        assert evaluation["descriptor_match"] is False, value
        assert evaluation["accepted"] is False


def test_verdict_shapes_attempt_binding(tmp_path):
    fingerprint = "b" * 64
    # The single-record verdict descriptor binds an attempt pin like
    # the flat shapes do.
    bound = evaluate_core_acceptance(
        _evidence_acceptance_descriptor(), fingerprint
    )
    assert bound["descriptor_match"] is True
    assert bound["attempt_bound"] is True
    assert "attempt_binding" not in bound["checks_not_performed"]

    other = evaluate_core_acceptance(
        _evidence_acceptance_descriptor(), "c" * 64
    )
    assert other["attempt_bound"] is False

    # The list descriptor pins list bytes — never a single record.
    listed = evaluate_core_acceptance(
        _evidence_list_acceptance_descriptor(), fingerprint
    )
    assert listed["descriptor_match"] is True
    assert listed["attempt_bound"] is False


def test_real_core_verdict_descriptors_fold(tmp_path, capsys):
    # Golden descriptors emitted by real Core —
    # `evidence accept --requirement --json` and
    # `evidence accept-list --requirement --json` — regenerate with a
    # built mumei when the descriptor shapes change.
    fixtures = Path(__file__).parent / "fixtures"
    for name in (
        "evidence_acceptance_single_requirement.json",
        "evidence_list_acceptance.json",
    ):
        descriptor = json.loads((fixtures / name).read_text())
        evaluation = evaluate_core_acceptance(descriptor)
        assert evaluation["descriptor_match"] is True, name
        assert evaluation["accepted"] is True, name

        evaluation = run_eval(
            __import__("argparse").Namespace(
                descriptor=str(fixtures / name),
                expected_fingerprint=None,
                output=None,
            )
        )
        assert evaluation["descriptor_match"] is True


def test_route_emits_descriptor_digest(capsys):
    # The route pins the assessed descriptor's raw bytes by
    # `descriptor_digest` — the carrier a signed-descriptor
    # verification binds to recover `descriptor_authenticity`.
    import argparse
    import hashlib

    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "evidence_acceptance_single_requirement.json"
    )
    evaluation = run_eval(
        argparse.Namespace(
            descriptor=str(fixture),
            expected_fingerprint=None,
            output=None,
        )
    )
    assert evaluation["descriptor_digest"] == hashlib.sha256(
        fixture.read_bytes()
    ).hexdigest()


def test_eval_doc_binds_to_descriptor_bytes():
    # `binding-eval` treats the eval doc's `descriptor_digest` as its
    # carrier: the eval doc binds to the descriptor it assessed, not
    # to its own bytes.
    import hashlib

    from agent.core_evidence import evaluate_evidence_binding

    descriptor_bytes = b'{"schema_version":"mumei.example/v1"}'
    descriptor_digest = hashlib.sha256(descriptor_bytes).hexdigest()
    eval_doc = {
        "schema_version": "mumei.core-acceptance-evaluation/v1",
        "descriptor_digest": descriptor_digest,
    }
    binding = evaluate_evidence_binding(descriptor_bytes, eval_doc)
    assert binding["carrier_match"] is True
    assert binding["bound"] is True
    # Its own bytes never bind — the carrier names the descriptor.
    eval_bytes = json.dumps(eval_doc).encode()
    assert (
        evaluate_evidence_binding(eval_bytes, eval_doc)["bound"] is False
    )
