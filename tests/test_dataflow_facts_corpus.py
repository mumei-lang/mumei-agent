"""Measure C05 dataflow-issue agreement against the labeled Go corpus.

Labels are corpus-declared expectations; counts measure agreement on this
corpus only, not soundness or completeness. There is no single score.
The corpus passes no contract outputs, so `contract_output_unassigned` is not
measured here.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path

import pytest

from agent import control_flow, dataflow_facts

_CORPUS_DIR = Path(__file__).parent / "fixtures" / "go_dataflow_corpus"
_CATEGORIES = (
    "nil_map_write",
    "lock_held_at_return",
    "resource_leak",
    "uninitialized_use",
    "send_on_closed_channel",
    "close_nil_channel",
    "use_after_close",
    "unlock_of_unlocked",
    "double_lock",
)
_ALLOWED_CATEGORIES = frozenset((*_CATEGORIES, "contract_output_unassigned"))
_ZERO = (0, 0, 0)


@dataclass(frozen=True)
class _Label:
    category: str
    subject: str


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
            parts = entry.strip().split()
            if (
                len(parts) != 2
                or parts[0] not in _ALLOWED_CATEGORIES
                or not dataflow_facts._norm(parts[1])
            ):
                raise ValueError(
                    f"unknown or malformed dataflow label on line "
                    f"{line_number}: {entry!r}"
                )
            parsed.append(_Label(parts[0], parts[1]))
        if not parsed:
            raise ValueError(f"empty dataflow label on line {line_number}")
        labels[line_number] = tuple(parsed)
    return labels


def _line_offsets(source: str) -> list[int]:
    offsets = [0]
    offsets.extend(
        index + 1 for index, character in enumerate(source) if character == "\n"
    )
    return offsets


def _label_offsets(
    source: str, labels: dict[int, tuple[_Label, ...]], line_offsets: list[int]
) -> dict[int, int]:
    result: dict[int, int] = {}
    for line_number in labels:
        start = line_offsets[line_number - 1]
        end = (
            line_offsets[line_number]
            if line_number < len(line_offsets)
            else len(source)
        )
        comment_start = source.find("//", start, end)
        assert comment_start >= 0
        result[line_number] = comment_start
    return result


def _metrics_for_file(
    path: Path,
) -> tuple[dict[str, tuple[int, int, int]], frozenset[str]]:
    source = path.read_text(encoding="utf-8")
    labels = _parse_labels(source)
    line_offsets = _line_offsets(source)
    label_offsets = _label_offsets(source, labels, line_offsets)
    units = control_flow.go_file_units(source)
    assert units.gaps == (), f"{path.name}: file-unit gaps: {units.gaps}"

    totals = {category: [0, 0, 0] for category in _CATEGORIES}
    unanalyzed: set[str] = set()

    def counts_for(category: str) -> list[int]:
        return totals.setdefault(category, [0, 0, 0])

    for function in units.functions:
        if function.body_span is None:
            continue
        function_labels = {
            line_number: line_labels
            for line_number, line_labels in labels.items()
            if function.body_span.start
            <= label_offsets[line_number]
            < function.body_span.end
        }
        body = control_flow.function_body(source, units, function)
        assert body == source[function.body_span.start : function.body_span.end]
        entry_names = control_flow.go_entry_assigned_names(source, units, function)
        # `param_names` is currently unused by the dataflow walker.
        flow = dataflow_facts.analyze_function(
            body, "go", param_names=set(entry_names)
        )
        if flow is None:
            unanalyzed.add(function.name)
            for line_labels in function_labels.values():
                for label in line_labels:
                    counts_for(label.category)[1] += 1
            continue

        matched: dict[int, set[int]] = {
            line_number: set() for line_number in function_labels
        }
        for issue in flow.issues:
            assert issue.category in _ALLOWED_CATEGORIES, (
                f"{path.name}:{function.name}: unexpected issue category "
                f"{issue.category!r}"
            )
            assert 0 <= issue.offset <= len(body)
            issue_line = bisect_right(
                line_offsets, function.body_span.start + issue.offset
            )
            issue_subject = dataflow_facts._norm(issue.subject)
            candidates = function_labels.get(issue_line, ())
            match_index = next(
                (
                    index
                    for index, label in enumerate(candidates)
                    if index not in matched[issue_line]
                    and label.category == issue.category
                    and dataflow_facts._norm(label.subject) == issue_subject
                ),
                None,
            )
            if match_index is None:
                counts_for(issue.category)[2] += 1
            else:
                matched[issue_line].add(match_index)
                counts_for(issue.category)[0] += 1

        for line_number, line_labels in function_labels.items():
            for index, label in enumerate(line_labels):
                if index not in matched[line_number]:
                    counts_for(label.category)[1] += 1

    return {category: tuple(counts) for category, counts in totals.items()}, frozenset(
        unanalyzed
    )


EXPECTED_METRICS: dict[str, dict[str, tuple[int, int, int]]] = {
    "channels.go": {
        "nil_map_write": _ZERO,
        "lock_held_at_return": _ZERO,
        "resource_leak": _ZERO,
        "uninitialized_use": _ZERO,
        "send_on_closed_channel": (2, 0, 0),
        "close_nil_channel": (1, 0, 0),
        "use_after_close": _ZERO,
        "unlock_of_unlocked": _ZERO,
        "double_lock": _ZERO,
    },
    "locks.go": {
        "nil_map_write": _ZERO,
        # Repeated `if c` conditions are not correlated across the branches,
        # so the walker retains a possible lock at function fallthrough.
        "lock_held_at_return": (1, 0, 1),
        "resource_leak": _ZERO,
        "uninitialized_use": _ZERO,
        "send_on_closed_channel": _ZERO,
        "close_nil_channel": _ZERO,
        "use_after_close": _ZERO,
        "unlock_of_unlocked": (2, 0, 0),
        "double_lock": (1, 0, 0),
    },
    "maps.go": {
        "nil_map_write": (2, 0, 0),
        "lock_held_at_return": _ZERO,
        "resource_leak": _ZERO,
        "uninitialized_use": _ZERO,
        "send_on_closed_channel": _ZERO,
        "close_nil_channel": _ZERO,
        "use_after_close": _ZERO,
        "unlock_of_unlocked": _ZERO,
        "double_lock": _ZERO,
    },
    "nil_values.go": {
        "nil_map_write": _ZERO,
        "lock_held_at_return": _ZERO,
        "resource_leak": _ZERO,
        "uninitialized_use": (4, 0, 0),
        "send_on_closed_channel": _ZERO,
        "close_nil_channel": _ZERO,
        "use_after_close": _ZERO,
        "unlock_of_unlocked": _ZERO,
        "double_lock": _ZERO,
    },
    "resources.go": {
        "nil_map_write": _ZERO,
        "lock_held_at_return": _ZERO,
        "resource_leak": (1, 0, 0),
        "uninitialized_use": _ZERO,
        "send_on_closed_channel": _ZERO,
        "close_nil_channel": _ZERO,
        "use_after_close": (1, 0, 0),
        "unlock_of_unlocked": _ZERO,
        "double_lock": _ZERO,
    },
}

EXPECTED_UNANALYSED: dict[str, frozenset[str]] = {
    filename: frozenset() for filename in EXPECTED_METRICS
}

EXPECTED_AGGREGATE: dict[str, tuple[int, int, int]] = {
    "nil_map_write": (2, 0, 0),
    # The single unexpected is the path-insensitive lock report in locks.go.
    "lock_held_at_return": (1, 0, 1),
    "resource_leak": (1, 0, 0),
    "uninitialized_use": (4, 0, 0),
    "send_on_closed_channel": (2, 0, 0),
    "close_nil_channel": (1, 0, 0),
    "use_after_close": (1, 0, 0),
    "unlock_of_unlocked": (2, 0, 0),
    "double_lock": (1, 0, 0),
}


def test_dataflow_corpus_files_parse_and_labels_are_inside_function_bodies():
    paths = sorted(_CORPUS_DIR.glob("*.go"))
    assert {path.name for path in paths} == set(EXPECTED_METRICS)
    assert set(EXPECTED_UNANALYSED) == set(EXPECTED_METRICS)

    for path in paths:
        source = path.read_text(encoding="utf-8")
        labels = _parse_labels(source)
        line_offsets = _line_offsets(source)
        label_offsets = _label_offsets(source, labels, line_offsets)
        units = control_flow.go_file_units(source)
        assert units.gaps == (), f"{path.name}: file-unit gaps: {units.gaps}"
        assert units.functions, f"{path.name}: no functions were parsed"
        for line_number, label_offset in label_offsets.items():
            assert any(
                function.body_span is not None
                and function.body_span.start <= label_offset < function.body_span.end
                for function in units.functions
            ), f"{path.name}:{line_number}: label is outside every function body"


@pytest.mark.parametrize(
    "source",
    (
        "// want: unknown_category x",
        "// want: resource_leak",
        "// want: nil_map_write m;",
    ),
)
def test_dataflow_corpus_rejects_unknown_or_malformed_labels(source: str):
    with pytest.raises(ValueError):
        _parse_labels(source)


def test_unmeasured_contract_output_label_is_still_counted(tmp_path: Path):
    path = tmp_path / "contract_output.go"
    path.write_text(
        "package p\nfunc f() int {\n\treturn 1 // want: "
        "contract_output_unassigned result\n}\n",
        encoding="utf-8",
    )

    metrics, unanalyzed = _metrics_for_file(path)

    assert metrics["contract_output_unassigned"] == (0, 1, 0)
    assert not unanalyzed


def test_dataflow_corpus_metrics_match_the_pinned_measurements():
    paths = sorted(_CORPUS_DIR.glob("*.go"))
    assert {path.name for path in paths} == set(EXPECTED_METRICS)
    aggregate = {category: [0, 0, 0] for category in _CATEGORIES}

    for path in paths:
        metrics, unanalyzed = _metrics_for_file(path)
        assert unanalyzed == EXPECTED_UNANALYSED[path.name], (
            f"{path.name}: unanalysed functions differ"
        )
        assert metrics == EXPECTED_METRICS[path.name], f"{path.name}: metrics differ"
        for category, counts in metrics.items():
            aggregate.setdefault(category, [0, 0, 0])
            for index, count in enumerate(counts):
                aggregate[category][index] += count

    assert {
        category: tuple(counts) for category, counts in aggregate.items()
    } == EXPECTED_AGGREGATE
