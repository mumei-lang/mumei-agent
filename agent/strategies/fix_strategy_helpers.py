"""Helper utilities for the fix strategy."""
from __future__ import annotations

import json
import logging
import re
import warnings
from pathlib import Path
from typing import Any

from agent import telemetry
from agent.pattern_library import PatternLibrary
from agent.spec_code_mapper import SpecCodeMapper

logger = logging.getLogger(__name__)

_SUPPORTED_LOSS_SCHEMA_VERSION = "p9-de/v1"


def json_dumps_loss_vector(loss_vector: dict) -> str:
    return json.dumps(loss_vector, indent=2, ensure_ascii=False)


class CyclicDependencyWarning(UserWarning):
    """Dependency graph contains a cycle; order requires manual review."""


_IMPORT_RE = re.compile(
    r"""^\s*(?:import|from|use)\s+(?P<target>["'][^"']+["']|[A-Za-z0-9_./:-]+)"""
)


def _parse_import_targets(source: str) -> list[str]:
    targets: list[str] = []
    for line in source.splitlines():
        code = line.split("//", 1)[0].split("#", 1)[0].strip()
        if not code:
            continue
        match = _IMPORT_RE.match(code)
        if match is None:
            continue
        target = match.group("target").strip().rstrip(";")
        if (target.startswith('"') and target.endswith('"')) or (
            target.startswith("'") and target.endswith("'")
        ):
            target = target[1:-1]
        if target:
            targets.append(target)
    return targets


def _candidate_import_paths(
    importing_file: Path,
    target: str,
    roots: set[Path],
) -> list[Path]:
    candidates: list[Path] = []
    raw = Path(target)
    if raw.suffix == ".mm" or "/" in target:
        candidates.append(raw if raw.is_absolute() else importing_file.parent / raw)
        for root in roots:
            candidates.append(root / raw)

    module = target.replace("::", ".").replace(".", "/")
    module_path = Path(module)
    for root in roots | {importing_file.parent}:
        candidates.append(root / module_path.with_suffix(".mm"))
        candidates.append(root / module_path / "mod.mm")
    return candidates


def build_dependency_graph(mm_files: list[Path]) -> dict[Path, list[Path]]:
    """Build a dependency graph where each file points to imported local files."""
    files = sorted({path.resolve() for path in mm_files})
    file_set = set(files)
    roots = {path.parent for path in files}
    graph: dict[Path, list[Path]] = {path: [] for path in files}

    for path in files:
        try:
            targets = _parse_import_targets(path.read_text(encoding="utf-8"))
        except OSError:
            targets = []
        dependencies: list[Path] = []
        for target in targets:
            for candidate in _candidate_import_paths(path, target, roots):
                resolved = candidate.resolve()
                if (
                    resolved in file_set
                    and resolved != path
                    and resolved not in dependencies
                ):
                    dependencies.append(resolved)
                    break
        graph[path] = sorted(dependencies)
    return graph


def topological_sort_files(graph: dict[Path, list[Path]]) -> list[Path]:
    """Return files in dependency-first order."""
    permanent: set[Path] = set()
    temporary: set[Path] = set()
    ordered: list[Path] = []
    cycle_nodes: set[Path] = set()

    def visit(node: Path, stack: list[Path]) -> None:
        if node in permanent:
            return
        if node in temporary:
            if node in stack:
                cycle_nodes.update(stack[stack.index(node):])
            else:
                cycle_nodes.add(node)
            return
        temporary.add(node)
        stack.append(node)
        for dependency in sorted(graph.get(node, [])):
            visit(dependency, stack)
        stack.pop()
        temporary.remove(node)
        permanent.add(node)
        ordered.append(node)

    for node in sorted(graph):
        visit(node, [])

    if cycle_nodes:
        cycle = ", ".join(str(path) for path in sorted(cycle_nodes))
        warnings.warn(
            f"cyclic .mm dependency detected; manual review required: {cycle}",
            CyclicDependencyWarning,
            stacklevel=2,
        )
    return ordered


def _aggregate_heal_results(results: list[dict]) -> dict:
    """Aggregate per-file heal results into a stable summary payload."""
    files: list[dict[str, object]] = []
    succeeded = 0
    failed = 0
    manual_review: list[object] = []

    for result in results:
        success = bool(result.get("success"))
        if success:
            succeeded += 1
        else:
            failed += 1
        entry: dict[str, object] = {
            "file": str(
                result.get("file")
                or result.get("code_file")
                or result.get("path")
                or ""
            ),
            "success": success,
            "attempts": int(result.get("attempts") or 0),
        }
        if result.get("error"):
            entry["error"] = str(result["error"])
        if result.get("note"):
            entry["note"] = str(result["note"])
        if result.get("manual_review_required"):
            entry["manual_review_required"] = result["manual_review_required"]
            manual_review.append(result["manual_review_required"])
        files.append(entry)

    payload: dict[str, object] = {
        "success": failed == 0,
        "total_files": len(results),
        "succeeded": succeeded,
        "failed": failed,
        "files": files,
    }
    if manual_review:
        payload["manual_review_required"] = manual_review
    return payload


def _nested_dict(value: object) -> dict[str, object] | None:
    if isinstance(value, dict):
        return value
    return None


def _structured_feedback(report_data: dict) -> dict[str, object]:
    return _nested_dict(report_data.get("structured_feedback")) or {}


def _reconstruction_loss_payload(report_data: dict) -> dict[str, object]:
    structured_loss = _nested_dict(_structured_feedback(report_data).get("reconstruction_loss"))
    if structured_loss is not None:
        return structured_loss
    semantic_feedback = _nested_dict(report_data.get("semantic_feedback")) or {}
    semantic_loss = _nested_dict(semantic_feedback.get("reconstruction_loss"))
    if semantic_loss is not None:
        return semantic_loss
    return _nested_dict(report_data.get("reconstruction_loss")) or {}


def _loss_vector(report_data: dict) -> list[float]:
    payload = _reconstruction_loss_payload(report_data)
    raw_vector = payload.get("loss_vector")
    if not isinstance(raw_vector, list):
        return []
    vector: list[float] = []
    for component in raw_vector:
        if isinstance(component, int | float):
            vector.append(float(component))
        elif isinstance(component, dict):
            magnitude = component.get("magnitude")
            if isinstance(magnitude, int | float):
                vector.append(float(magnitude))
    return vector


def _loss_counterexample(report_data: dict) -> dict[str, object]:
    payload = _reconstruction_loss_payload(report_data)
    return _nested_dict(payload.get("counter_example")) or _nested_dict(
        report_data.get("counterexample")
    ) or {}


def _loss_schema_version(report_data: dict) -> str:
    payload = _reconstruction_loss_payload(report_data)
    schema_version = payload.get("schema_version")
    return schema_version if isinstance(schema_version, str) else ""


def _loss_schema_supported(report_data: dict) -> bool:
    schema_version = _loss_schema_version(report_data)
    return schema_version in {"", _SUPPORTED_LOSS_SCHEMA_VERSION}


def _classify_structured_error(report_data: dict) -> str:
    feedback = _structured_feedback(report_data)
    error_type = feedback.get("error_type")
    if isinstance(error_type, str) and error_type:
        return error_type
    payload = _reconstruction_loss_payload(report_data)
    violated_property = payload.get("violated_property")
    property_text = violated_property.lower() if isinstance(violated_property, str) else ""
    counterexample = _loss_counterexample(report_data)
    divisor_is_zero = counterexample.get("divisor") == 0
    slash_divisor_is_zero = counterexample.get("b") == 0 and "/" in property_text
    if divisor_is_zero or slash_divisor_is_zero:
        return "division_by_zero"
    if "requires" in property_text:
        return "precondition_violated"
    if "ensures" in property_text or "result" in property_text:
        return "postcondition_violated"
    return ""


def _repair_strategy_for_error(error_type: str, vector: list[float]) -> str:
    if error_type == "division_by_zero":
        return "strengthen_nonzero_precondition"
    if error_type == "postcondition_violated":
        return "repair_body_to_reduce_l_recon"
    if error_type == "precondition_violated":
        return "repair_callsite_or_requires"
    if error_type == "invariant_violated":
        return "repair_invariant_constraint"
    if any(abs(component) > 0.0 for component in vector):
        return "target_largest_loss_component"
    return "generic_verifier_repair"


def interpret_structured_feedback(report_data: dict) -> dict[str, object]:
    vector = _loss_vector(report_data)
    error_type = (
        report_data.get("failure_type")
        if isinstance(report_data.get("failure_type"), str)
        else ""
    ) or _classify_structured_error(report_data)
    magnitude = sum(abs(component) for component in vector)
    return {
        "error_type": error_type or "unknown",
        "loss_magnitude": magnitude,
        "repair_strategy": _repair_strategy_for_error(error_type, vector),
        "counterexample": _loss_counterexample(report_data),
        "schema_version": _loss_schema_version(report_data) or "legacy",
        "schema_supported": _loss_schema_supported(report_data),
    }


def _format_loss_vector_guidance(report_data: dict) -> str:
    payload = _reconstruction_loss_payload(report_data)
    if not payload:
        return ""
    vector = _loss_vector(report_data)
    interpretation = interpret_structured_feedback(report_data)
    counterexample = _loss_counterexample(report_data)
    violated_property = payload.get("violated_property", "")
    lines = [
        "Structured feedback loss vector:",
        f"- violated_property: {violated_property}",
        f"- loss_vector: {vector}",
        f"- total L_recon: {interpretation['loss_magnitude']}",
        f"- selected repair strategy: {interpretation['repair_strategy']}",
    ]
    if counterexample:
        pairs = ", ".join(f"{key}={value}" for key, value in counterexample.items())
        lines.append(f"- counterexample: {pairs}")
    lines.append("Prioritize edits that reduce non-zero L_recon components without weakening the contract.")
    return "\n".join(lines)


def response_token_count(response: object) -> int:
    try:
        usage = response.usage
    except AttributeError:
        return 0
    if usage is None:
        return 0
    if isinstance(usage, dict):
        total_tokens = usage.get("total_tokens")
    else:
        try:
            total_tokens = usage.total_tokens
        except AttributeError:
            return 0
    try:
        count = int(total_tokens or 0)
    except (TypeError, ValueError):
        return 0
    # Parallel OTel channel; independent of Metrics.record_tokens and never
    # affects the JSON metrics output.  No-op unless OTel is enabled.
    telemetry.record_llm_tokens(count)
    return count

def _update_spec_code_mapping(
    report_data: dict,
    spec: dict | None,
    fixed_code: str,
    enabled: bool | None,
) -> None:
    """Update structured report mapping metadata after a fix."""
    if not enabled or not spec or not fixed_code:
        return
    try:
        mapper = SpecCodeMapper()
        result = mapper.build_mapping(spec, fixed_code, report_data)
        report_data["spec_code_mapping"] = mapper.to_json(result.mappings)
    except Exception:
        logging.getLogger(__name__).warning(
            "Failed to update spec-code mapping after fix",
            exc_info=True,
        )


def _record_pattern(
    pattern_library: PatternLibrary | None,
    violation_type: str,
    failure_type: str,
    source_before: str,
    source_after: str,
    report: dict,
    *,
    fix_method: str = "llm",
) -> None:
    """Record a successful fix pattern if a pattern library is provided."""
    if pattern_library is None:
        return
    try:
        pattern_library.record(
            violation_type=violation_type,
            failure_type=failure_type,
            source_before=source_before,
            source_after=source_after,
            report=report,
            fix_method=fix_method,
        )
    except Exception:
        logging.getLogger(__name__).warning(
            "Failed to record pattern to library",
            exc_info=True,
        )
