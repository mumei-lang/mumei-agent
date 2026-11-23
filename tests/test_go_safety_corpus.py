"""Measure C05 Go division/bounds safety agreement on authored fixtures.

Labels mark runtime panics expected by this corpus, with no contracts supplied.
Counts measure agreement on this corpus only, not soundness or completeness;
there is no single score.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from agent import control_flow
from agent.strategies.foreign_code_strategy_helpers import _detect_go_safety_issues

_CORPUS_DIR = Path(__file__).parent / "fixtures" / "go_safety_corpus"
_CATEGORIES = ("division_by_zero", "index_out_of_bounds")
_ZERO = (0, 0, 0)


@dataclass(frozen=True)
class _Label:
    category: str
    subject: str


def _norm(subject: str) -> str:
    return "".join(subject.split())


def _parse_labels(source: str) -> dict[int, tuple[_Label, ...]]:
    labels: dict[int, tuple[_Label, ...]] = {}
    for line_number, line in enumerate(source.splitlines(), start=1):
        comment_start = line.find("//")
        if comment_start < 0:
            continue
        comment = line[comment_start + 2 :].strip()
        if not comment.startswith("want:"):
            continue
        payload = comment[len("want:") :].strip()
        parsed: list[_Label] = []
        for entry in payload.split(";"):
            parts = entry.strip().split(maxsplit=1)
            if (
                len(parts) != 2
                or parts[0] not in _CATEGORIES
                or not _norm(parts[1])
            ):
                raise ValueError(
                    f"unknown or malformed Go safety label on line "
                    f"{line_number}: {entry!r}"
                )
            parsed.append(_Label(parts[0], parts[1].strip()))
        if not parsed:
            raise ValueError(f"empty Go safety label on line {line_number}")
        labels[line_number] = tuple(parsed)
    return labels


def _line_offsets(source: str) -> list[int]:
    offsets = [0]
    offsets.extend(
        index + 1 for index, character in enumerate(source) if character == "\n"
    )
    return offsets


def _label_functions(
    source: str,
    labels: dict[int, tuple[_Label, ...]],
    line_offsets: list[int],
    units: control_flow.GoFileUnits,
    filename: str,
) -> dict[int, str]:
    result: dict[int, str] = {}
    for line_number in labels:
        start = line_offsets[line_number - 1]
        end = line_offsets[line_number] if line_number < len(line_offsets) else len(source)
        label_offset = source.find("//", start, end)
        assert label_offset >= 0
        owners = [
            function
            for function in units.functions
            if function.body_span is not None
            and function.body_span.start <= label_offset < function.body_span.end
        ]
        assert len(owners) == 1, (
            f"{filename}:{line_number}: expected one function body, got "
            f"{[function.name for function in owners]}"
        )
        result[line_number] = owners[0].name
    return result


def _classify_message(message: str) -> tuple[str, str] | None:
    for category, marker in (
        ("division_by_zero", "can divide by `"),
        ("index_out_of_bounds", "can index `"),
    ):
        start = message.find(marker)
        if start < 0:
            continue
        subject_start = start + len(marker)
        subject_end = message.find("`", subject_start)
        if subject_end >= 0:
            return category, message[subject_start:subject_end]
    return None


def _metrics_for_file(
    path: Path,
) -> tuple[
    dict[str, tuple[int, int, int]],
    frozenset[tuple[str, str, str]],
    frozenset[tuple[str, str, str]],
    frozenset[tuple[str, str]],
]:
    source = path.read_text(encoding="utf-8")
    labels = _parse_labels(source)
    units = control_flow.go_file_units(source)
    assert units.gaps == (), f"{path.name}: file-unit gaps: {units.gaps}"
    line_offsets = _line_offsets(source)
    label_functions = _label_functions(
        source, labels, line_offsets, units, path.name
    )

    totals = {category: [0, 0, 0] for category in _CATEGORIES}
    matched_labels: set[tuple[int, int]] = set()
    missed: set[tuple[str, str, str]] = set()
    unexpected: set[tuple[str, str, str]] = set()
    other: set[tuple[str, str]] = set()

    # The detector is measured once for each complete fixture file.
    issues = _detect_go_safety_issues(source)
    for issue in issues:
        classification = _classify_message(issue.message)
        if classification is None:
            other.add((issue.function_name, issue.message))
            continue
        category, subject = classification
        normalized_subject = _norm(subject)
        candidate = next(
            (
                (line_number, index)
                for line_number, line_labels in labels.items()
                if label_functions[line_number] == issue.function_name
                for index, label in enumerate(line_labels)
                if (line_number, index) not in matched_labels
                and label.category == category
                and _norm(label.subject) == normalized_subject
            ),
            None,
        )
        if candidate is None:
            totals[category][2] += 1
            unexpected.add((issue.function_name, category, normalized_subject))
        else:
            matched_labels.add(candidate)
            totals[category][0] += 1

    for line_number, line_labels in labels.items():
        function_name = label_functions[line_number]
        for index, label in enumerate(line_labels):
            if (line_number, index) not in matched_labels:
                totals[label.category][1] += 1
                missed.add((function_name, label.category, _norm(label.subject)))

    return (
        {category: tuple(counts) for category, counts in totals.items()},
        frozenset(missed),
        frozenset(unexpected),
        frozenset(other),
    )


EXPECTED_METRICS: dict[str, dict[str, tuple[int, int, int]]] = {
    "division.go": {
        "division_by_zero": (4, 2, 0),
        "index_out_of_bounds": _ZERO,
    },
    "bounds.go": {
        "division_by_zero": _ZERO,
        "index_out_of_bounds": (5, 0, 0),
    },
}

EXPECTED_MISSED: dict[str, frozenset[tuple[str, str, str]]] = {
    "division.go": frozenset(
        {
            # division.go:4 — helpers.py:5235-5236 marks b non-zero via the
            # Div-name and sole-return-divisor heuristics.
            ("Div", "division_by_zero", "b"),
            # division.go:8 — helpers.py:5235-5236 applies the same two
            # non-zero parameter heuristics to Mod.
            ("Mod", "division_by_zero", "b"),
        }
    ),
    "bounds.go": frozenset(),
}

EXPECTED_UNEXPECTED: dict[str, frozenset[tuple[str, str, str]]] = {
    "division.go": frozenset(),
    "bounds.go": frozenset(),
}

EXPECTED_OTHER: dict[str, frozenset[tuple[str, str]]] = {
    "division.go": frozenset(),
    "bounds.go": frozenset(
        {
            (
                "Index",
                (
                    "Go function `Index` indexes with `i` without the bounds guard "
                    "that sibling `IndexGuarded` applies to the same parameter "
                    "(sibling-guard asymmetry)"
                ),
            )
        }
    ),
}

EXPECTED_AGGREGATE: dict[str, tuple[int, int, int]] = {
    "division_by_zero": (4, 2, 0),
    "index_out_of_bounds": (5, 0, 0),
}


def test_go_safety_corpus_files_parse_and_labels_are_inside_function_bodies():
    paths = sorted(_CORPUS_DIR.glob("*.go"))
    assert {path.name for path in paths} == set(EXPECTED_METRICS)
    assert set(EXPECTED_MISSED) == set(EXPECTED_METRICS)
    assert set(EXPECTED_UNEXPECTED) == set(EXPECTED_METRICS)
    assert set(EXPECTED_OTHER) == set(EXPECTED_METRICS)

    for path in paths:
        source = path.read_text(encoding="utf-8")
        labels = _parse_labels(source)
        units = control_flow.go_file_units(source)
        assert units.gaps == (), f"{path.name}: file-unit gaps: {units.gaps}"
        assert units.functions, f"{path.name}: no functions were parsed"
        _label_functions(source, labels, _line_offsets(source), units, path.name)


@pytest.mark.parametrize(
    "source",
    (
        "// want: unknown_category x",
        "// want: division_by_zero",
        "// want: index_out_of_bounds ;",
        "// want: division_by_zero x; unknown_category y",
    ),
)
def test_go_safety_corpus_rejects_unknown_or_malformed_labels(source: str):
    with pytest.raises(ValueError):
        _parse_labels(source)


def test_go_safety_corpus_normalizes_whitespace_in_subjects():
    labels = _parse_labels("// want: index_out_of_bounds s [len(s) - 1]")

    assert _norm(labels[1][0].subject) == "s[len(s)-1]"


def test_go_safety_corpus_metrics_match_the_pinned_measurements():
    paths = sorted(_CORPUS_DIR.glob("*.go"))
    assert {path.name for path in paths} == set(EXPECTED_METRICS)
    aggregate = {category: [0, 0, 0] for category in _CATEGORIES}

    for path in paths:
        metrics, missed, unexpected, other = _metrics_for_file(path)
        assert metrics == EXPECTED_METRICS[path.name], f"{path.name}: metrics differ"
        assert missed == EXPECTED_MISSED[path.name], f"{path.name}: missed labels differ"
        assert unexpected == EXPECTED_UNEXPECTED[path.name], (
            f"{path.name}: unexpected issues differ"
        )
        assert other == EXPECTED_OTHER[path.name], f"{path.name}: other issues differ"
        for category, counts in metrics.items():
            for index, count in enumerate(counts):
                aggregate[category][index] += count

    assert {
        category: tuple(counts) for category, counts in aggregate.items()
    } == EXPECTED_AGGREGATE
