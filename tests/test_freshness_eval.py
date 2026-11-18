"""Route tests for ``freshness-eval``: evaluating a declared record's
``produced_at`` freshness claim against a declared clock, emitting
``mumei.freshness-evaluation/v1``.

The fold never reads the system clock — ``--reference-time`` is the
caller's declared reference — and reports observations only:
``clock_authenticity``, ``producer_time_authenticity`` and
``freshness_enforcement`` stay unperformed."""

import json
from pathlib import Path

import pytest

from agent.core_evidence import evaluate_freshness
from agent.freshness_eval import (
    build_eval_parser,
    main_eval,
)

_PRODUCED = "2026-11-18T00:00:00Z"
_REFERENCE = "2026-11-18T01:00:00Z"


def _write(path: Path, value) -> Path:
    path.write_text(json.dumps(value) if not isinstance(value, str) else value)
    return path


def _args(parser, record_path, *extra):
    return parser.parse_args(
        [
            "--record",
            str(record_path),
            "--reference-time",
            _REFERENCE,
            "--max-age-seconds",
            "7200",
            *extra,
        ]
    )


def test_fresh_record_within_window():
    evaluation = evaluate_freshness(
        {"produced_at": _PRODUCED}, _REFERENCE, 7200
    )
    assert evaluation["schema_version"] == "mumei.freshness-evaluation/v1"
    assert evaluation["freshness_claimed"] is True
    assert evaluation["within_window"] is True
    assert set(evaluation["checks_not_performed"]) == {
        "clock_authenticity",
        "producer_time_authenticity",
        "freshness_enforcement",
    }


def test_stale_and_future_records_fail_window():
    # Older than the window.
    evaluation = evaluate_freshness(
        {"produced_at": _PRODUCED}, _REFERENCE, 1800
    )
    assert evaluation["freshness_claimed"] is True
    assert evaluation["within_window"] is False

    # Postdated claims never count as fresh.
    evaluation = evaluate_freshness(
        {"produced_at": "2026-11-19T00:00:00Z"}, _REFERENCE, 7200
    )
    assert evaluation["freshness_claimed"] is True
    assert evaluation["within_window"] is False


def test_missing_or_malformed_claim():
    for record in (
        {},
        {"produced_at": "not-a-time"},
        {"produced_at": "2026-11-18T00:00:00"},  # no timezone
        {"produced_at": 7},
        {"produced_at": None},
    ):
        evaluation = evaluate_freshness(record, _REFERENCE, 7200)
        assert evaluation["freshness_claimed"] is False
        assert evaluation["within_window"] is False


def test_offset_timestamps_parse():
    evaluation = evaluate_freshness(
        {"produced_at": "2026-11-18T09:30:00+09:00"},
        _REFERENCE,
        7200,
    )
    assert evaluation["freshness_claimed"] is True
    assert evaluation["within_window"] is True


def test_request_validation():
    with pytest.raises(ValueError):
        evaluate_freshness("not-a-dict", _REFERENCE, 7200)
    with pytest.raises(ValueError):
        evaluate_freshness({"produced_at": _PRODUCED}, "bad-time", 7200)
    with pytest.raises(ValueError):
        evaluate_freshness(
            {"produced_at": _PRODUCED}, _REFERENCE, -1
        )
    with pytest.raises(ValueError):
        evaluate_freshness(
            {"produced_at": _PRODUCED}, _REFERENCE, "1h"
        )


def test_route_emits_evaluation(tmp_path, capsys):
    record = _write(tmp_path / "rec.json", {"produced_at": _PRODUCED})
    import argparse

    parser = argparse.ArgumentParser()
    build_eval_parser(parser)
    exit_code = main_eval(_args(parser, record))
    assert exit_code == 0
    emitted = json.loads(capsys.readouterr().out)
    assert emitted["freshness_claimed"] is True
    assert emitted["within_window"] is True


def test_route_output_file(tmp_path, capsys):
    record = _write(tmp_path / "rec.json", {"produced_at": _PRODUCED})
    out = tmp_path / "out.json"
    import argparse

    parser = argparse.ArgumentParser()
    build_eval_parser(parser)
    exit_code = main_eval(_args(parser, record, "--output", str(out)))
    assert exit_code == 0
    emitted = json.loads(out.read_text())
    assert emitted["within_window"] is True


def test_route_static_failures(tmp_path, capsys):
    import argparse

    parser = argparse.ArgumentParser()
    build_eval_parser(parser)

    missing = tmp_path / "missing.json"
    assert main_eval(_args(parser, missing)) == 1
    assert "freshness-eval:" in capsys.readouterr().err

    malformed = _write(tmp_path / "bad.json", "{not json")
    assert main_eval(_args(parser, malformed)) == 1

    non_object = _write(tmp_path / "list.json", [1, 2])
    assert main_eval(_args(parser, non_object)) == 1

    record = _write(tmp_path / "rec.json", {"produced_at": _PRODUCED})
    assert (
        main_eval(
            parser.parse_args(
                [
                    "--record",
                    str(record),
                    "--reference-time",
                    "bad",
                    "--max-age-seconds",
                    "10",
                ]
            )
        )
        == 1
    )
    assert (
        main_eval(
            parser.parse_args(
                [
                    "--record",
                    str(record),
                    "--reference-time",
                    _REFERENCE,
                    "--max-age-seconds",
                    "-5",
                ]
            )
        )
        == 1
    )


def test_route_refuses_output_over_input(tmp_path):
    record = _write(tmp_path / "rec.json", {"produced_at": _PRODUCED})
    import argparse

    parser = argparse.ArgumentParser()
    build_eval_parser(parser)
    assert (
        main_eval(_args(parser, record, "--output", str(record)))
        == 1
    )
