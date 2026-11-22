"""Measure C05 flow-hint agreement against the labeled Go fixture corpus.

`unassigned` labels reads of function-local names without an explicit
assignment (`:=`, `=`, initialized `var`, or range/select binding) reaching on
every path from function entry. A bare zero-value `var x T` is not an explicit
assignment; parameters, named results, and package-level names count as
assigned on entry and are never labeled unassigned.

`unused` labels explicit stores to function-local names that no later read can
observe. Package-level stores, parameter pointees, fields, and elements are
never labeled unused. `unreachable` labels are unchanged.

Labels are corpus-declared expectations; counts measure agreement on this
corpus only, not soundness or completeness. The family counts stay separate:
there is no single quality score.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path

import pytest

from agent import control_flow

_CORPUS_DIR = Path(__file__).parent / "fixtures" / "go_flow_corpus"
_FAMILIES = ("unassigned", "unused", "unreachable")
_LABEL_KINDS = frozenset(_FAMILIES)

_METRIC_ZERO = (0, 0, 0)

# The CFG layer resolves backward goto; the dataflow walker has a separate
# forward-goto boundary.
EXPECTED_GAPS: dict[str, dict[str, tuple[str, ...]]] = {}

EXPECTED_UNRELIABLE: dict[str, dict[str, frozenset[str]]] = {
    "unreliable_names.go": {
        "closureAssignedName": frozenset({"state"}),
        "addressTakenName": frozenset({"state"}),
    },
}

EXPECTED_METRICS: dict[str, dict[str, tuple[int, int, int]]] = {
    "backward_goto.go": {
        "unassigned": (0, 1, 0),  # Bare var is counted as assigned by the hint.
        "unused": _METRIC_ZERO,
        "unreachable": _METRIC_ZERO,
    },
    "clean.go": {
        "unassigned": _METRIC_ZERO,
        "unused": _METRIC_ZERO,
        "unreachable": _METRIC_ZERO,
    },
    "dead_store.go": {
        "unassigned": _METRIC_ZERO,
        "unused": (0, 1, 0),  # The later read masks the overwritten store.
        "unreachable": _METRIC_ZERO,
    },
    "defer.go": {
        "unassigned": (0, 1, 0),  # Bare var is counted as assigned by the hint.
        "unused": _METRIC_ZERO,
        "unreachable": _METRIC_ZERO,
    },
    "entry_assigned_names.go": {
        "unassigned": (0, 0, 2),  # Parameter and package entry values are not seeded.
        "unused": _METRIC_ZERO,
        "unreachable": _METRIC_ZERO,
    },
    "expression_switch.go": {
        "unassigned": (0, 1, 0),  # Bare var is counted as assigned by the hint.
        "unused": _METRIC_ZERO,
        "unreachable": _METRIC_ZERO,
    },
    "forward_goto.go": {
        "unassigned": (0, 1, 0),  # Bare var is counted as assigned by the hint.
        "unused": _METRIC_ZERO,
        "unreachable": _METRIC_ZERO,
    },
    "loop_carried.go": {
        "unassigned": (0, 2, 0),  # Bare var is counted as assigned by the hint.
        "unused": _METRIC_ZERO,
        "unreachable": _METRIC_ZERO,
    },
    "loop_jumps.go": {
        "unassigned": _METRIC_ZERO,
        "unused": (2, 0, 0),
        "unreachable": (2, 0, 0),
    },
    "partial_branch.go": {
        "unassigned": (0, 1, 0),  # Bare var is counted as assigned by the hint.
        "unused": _METRIC_ZERO,
        "unreachable": _METRIC_ZERO,
    },
    "select.go": {
        "unassigned": (0, 1, 0),  # Bare var is counted as assigned by the hint.
        "unused": _METRIC_ZERO,
        "unreachable": _METRIC_ZERO,
    },
    "straight_line.go": {
        "unassigned": (0, 1, 0),  # Bare var is counted as assigned by the hint.
        "unused": (1, 0, 0),
        "unreachable": _METRIC_ZERO,
    },
    "type_switch.go": {
        "unassigned": (0, 1, 0),  # Bare var is counted as assigned by the hint.
        "unused": _METRIC_ZERO,
        "unreachable": _METRIC_ZERO,
    },
    "unreachable_return_panic.go": {
        "unassigned": _METRIC_ZERO,
        "unused": (2, 0, 0),
        "unreachable": (2, 0, 0),
    },
    "unreliable_names.go": {
        "unassigned": (0, 2, 0),  # Bare var is counted despite unreliable writes.
        "unused": _METRIC_ZERO,
        "unreachable": _METRIC_ZERO,
    },
}

EXPECTED_AGGREGATE: dict[str, tuple[int, int, int]] = {
    "unassigned": (0, 12, 2),  # Bare vars count; entry-assigned names are not seeded.
    "unused": (5, 1, 0),  # The later read hides the dead store.
    "unreachable": (4, 0, 0),
}


@dataclass(frozen=True)
class _Label:
    kind: str
    name: str | None = None


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
        entries = [entry.strip() for entry in payload.split(";")]
        parsed: list[_Label] = []
        for entry in entries:
            parts = entry.split()
            if parts == ["unreachable"]:
                parsed.append(_Label("unreachable"))
            elif (
                len(parts) == 2
                and parts[0] in {"unassigned", "unused"}
                and parts[1].isidentifier()
            ):
                parsed.append(_Label(parts[0], parts[1]))
            else:
                raise ValueError(
                    f"unknown or malformed flow label on line {line_number}: "
                    f"{entry!r}"
                )
        if not parsed:
            raise ValueError(f"empty flow label on line {line_number}")
        labels[line_number] = tuple(parsed)
    return labels


def _line_offsets(source: str) -> list[int]:
    offsets = [0]
    offsets.extend(
        index + 1 for index, character in enumerate(source) if character == "\n"
    )
    return offsets


def _metrics_for_file(path: Path) -> dict[str, tuple[int, int, int]]:
    source = path.read_text(encoding="utf-8")
    labels = _parse_labels(source)
    line_offsets = _line_offsets(source)
    units = control_flow.go_file_units(source)
    assert units.gaps == (), f"{path.name}: file-unit gaps: {units.gaps}"

    totals = {family: [0, 0, 0] for family in _FAMILIES}
    expected_gaps = EXPECTED_GAPS.get(path.name, {})
    seen_gaps: set[str] = set()
    expected_unreliable = EXPECTED_UNRELIABLE.get(path.name, {})
    seen_unreliable: set[str] = set()
    consumed_label_lines: set[int] = set()

    for function in units.functions:
        if function.body_span is None:
            continue
        body = control_flow.function_body(source, units, function)
        assert body is not None
        function_labels = {
            line_number: line_labels
            for line_number, line_labels in labels.items()
            if function.body_span.start
            <= line_offsets[line_number - 1]
            < function.body_span.end
        }
        construction = control_flow.build_go_cfg(body)
        if construction.gaps or construction.graph is None:
            assert function.name in expected_gaps, (
                f"{path.name}:{function.name}: undeclared CFG gap "
                f"{construction.gaps}"
            )
            actual_reasons = tuple(gap.reason for gap in construction.gaps)
            assert actual_reasons == expected_gaps[function.name]
            assert not function_labels, (
                f"{path.name}:{function.name}: labels cannot map through a CFG gap"
            )
            seen_gaps.add(function.name)
            continue

        assert function.name not in expected_gaps, (
            f"{path.name}:{function.name}: declared CFG gap was not observed"
        )
        graph = construction.graph
        nodes_by_line: dict[int, list[control_flow.CFGNode]] = {}
        for node in graph.nodes:
            if node.span is None:
                continue
            source_line = bisect_right(
                line_offsets, function.body_span.start + node.span.start
            )
            nodes_by_line.setdefault(source_line, []).append(node)

        expectations = {
            "unassigned": [],
            "unused": [],
            "unreachable": [],
        }
        for source_line, line_labels in function_labels.items():
            candidates = nodes_by_line.get(source_line, [])
            assert len(candidates) == 1, (
                f"{path.name}:{source_line}: expected one CFG node starting "
                f"on the label line, found {len(candidates)}"
            )
            node = candidates[0]
            for label in line_labels:
                if label.kind in {"unassigned", "unused"}:
                    assert label.name is not None
                    expectations[label.kind].append((node.node_id, label.name))
                else:
                    expectations[label.kind].append(node.node_id)
        consumed_label_lines.update(function_labels)

        hints = control_flow.flow_hints(body, graph)
        unreliable_names = expected_unreliable.get(
            function.name, frozenset()
        )
        if unreliable_names:
            seen_unreliable.add(function.name)
            assert unreliable_names <= hints.unreliable
            assert all(
                not finding.definite
                for finding in hints.unassigned
                if finding.name in unreliable_names
            )

        measured = control_flow.evaluate_flow_hints(
            hints,
            control_flow.HintExpectations(
                unassigned=tuple(expectations["unassigned"]),
                unused=tuple(expectations["unused"]),
                unreachable=tuple(expectations["unreachable"]),
            ),
        )
        for family in _FAMILIES:
            family_metrics = getattr(measured, family)
            counts = (
                family_metrics.matched,
                family_metrics.missed,
                family_metrics.unexpected,
            )
            totals[family] = [
                total + count
                for total, count in zip(totals[family], counts, strict=True)
            ]

    assert seen_gaps == set(expected_gaps), (
        f"{path.name}: declared CFG gaps not observed: "
        f"{set(expected_gaps) - seen_gaps}"
    )
    assert seen_unreliable == set(expected_unreliable), (
        f"{path.name}: unreliable-name declarations not observed"
    )
    assert consumed_label_lines == set(labels), (
        f"{path.name}: labels outside mapped function bodies: "
        f"{set(labels) - consumed_label_lines}"
    )
    return {
        family: (counts[0], counts[1], counts[2])
        for family, counts in totals.items()
    }


def test_flow_hint_corpus_metrics_match_pinned_per_file_counts() -> None:
    paths = sorted(_CORPUS_DIR.glob("*.go"))
    assert {path.name for path in paths} == set(EXPECTED_METRICS)
    actual = {path.name: _metrics_for_file(path) for path in paths}
    assert actual == EXPECTED_METRICS

    aggregate = {
        family: tuple(
            sum(actual[file_name][family][index] for file_name in actual)
            for index in range(3)
        )
        for family in _FAMILIES
    }
    for family in _FAMILIES:
        assert aggregate[family] == EXPECTED_AGGREGATE[family]


def test_corpus_labels_parse_known_kinds_and_cover_every_family() -> None:
    paths = sorted(_CORPUS_DIR.glob("*.go"))
    seen_families: set[str] = set()
    for path in paths:
        labels = _parse_labels(path.read_text(encoding="utf-8"))
        seen_families.update(
            label.kind
            for line_labels in labels.values()
            for label in line_labels
        )
    assert seen_families == _LABEL_KINDS
    assert _parse_labels(
        (_CORPUS_DIR / "clean.go").read_text(encoding="utf-8")
    ) == {}
    assert _parse_labels(
        (_CORPUS_DIR / "entry_assigned_names.go").read_text(encoding="utf-8")
    ) == {}

    with pytest.raises(ValueError, match="unknown or malformed flow label"):
        _parse_labels("package main\nfunc f() { x = 1 // want: future x\n}")
