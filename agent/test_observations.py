"""Helpers for checking harvested test behavior against extracted specs."""
from __future__ import annotations

import copy
import json
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from agent.extract_spec_helpers import _spec_to_contradiction_check_module


_VERDICTS = (
    "consistent",
    "contradicts_ensures",
    "inconclusive",
    "not_checked",
    "outside_requires",
    "rejection_explained",
    "requires_admits_rejected",
)
_BLOCKING_VERDICTS = {"contradicts_ensures", "requires_admits_rejected"}


class ObservationCheckError(ValueError):
    """Raised when mumei cannot produce a valid observation-check report."""


def spec_to_observe_module(spec: dict) -> str:
    """Render trusted atoms with the extracted spec's real signatures."""
    return _spec_to_contradiction_check_module(spec)


def _language_for_observation(observation: dict[str, Any]) -> str | None:
    suffix = Path(str(observation.get("file", ""))).suffix.lower()
    return {".py": "python", ".rs": "rust"}.get(suffix)


def _target_params(
    harvest: dict[str, Any],
    target: str,
    language: str | None,
) -> list[str] | None:
    targets = harvest.get("targets")
    target_info = targets.get(target) if isinstance(targets, dict) else None
    if not isinstance(target_info, dict) or language is None:
        return None
    language_info = target_info.get(language)
    if not isinstance(language_info, dict):
        return None
    params = language_info.get("params")
    if not isinstance(params, list) or not all(
        isinstance(name, str) for name in params
    ):
        return None
    return params


def align_harvest_to_spec(harvest: dict, spec: dict) -> dict:
    """Copy harvest observations into spec parameter order when names agree."""
    aligned = copy.deepcopy(harvest)
    observations = aligned.get("observations")
    if not isinstance(observations, list):
        return aligned
    for observation in observations:
        if not isinstance(observation, dict) or not isinstance(
            observation.get("args"), dict
        ):
            continue
        params = _target_params(
            harvest,
            str(observation.get("target", "")),
            _language_for_observation(observation),
        )
        args = observation["args"]
        if params is not None and set(args) == set(params):
            observation["args"] = [args[name] for name in params]
    return aligned


def check_observations(
    module_path_or_source: str | Path,
    harvest: dict,
    mumei_client,
) -> dict:
    """Run mumei observe in an isolated directory and validate its report."""
    with tempfile.TemporaryDirectory(prefix="mumei-observe-tests-") as tmp:
        tmp_path = Path(tmp)
        if isinstance(module_path_or_source, Path):
            module_path = module_path_or_source
        else:
            candidate = Path(module_path_or_source)
            try:
                is_file = "\n" not in module_path_or_source and candidate.is_file()
            except OSError:
                is_file = False
            module_path = candidate if is_file else tmp_path / "observe.mm"
            if module_path == tmp_path / "observe.mm":
                module_path.write_text(module_path_or_source, encoding="utf-8")
        harvest_path = tmp_path / "harvest.json"
        harvest_path.write_text(
            json.dumps(harvest, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        result = mumei_client.observe_check(str(module_path), str(harvest_path))

    if not isinstance(result, dict):
        raise ObservationCheckError("mumei observe returned an invalid response")
    returncode = result.get("returncode")
    stderr = str(result.get("stderr") or "").strip()
    if returncode not in (0, 1):
        message = f"mumei observe failed with exit code {returncode}"
        raise ObservationCheckError(f"{message}: {stderr}" if stderr else message)
    report = result.get("report")
    if not isinstance(report, dict):
        message = "mumei observe returned no JSON report"
        raise ObservationCheckError(f"{message}: {stderr}" if stderr else message)
    if report.get("schema") != "mumei.observation-check/v1":
        raise ObservationCheckError(
            "mumei observe returned an unexpected report schema: "
            f"{report.get('schema')!r}"
        )
    if not isinstance(report.get("results"), list):
        raise ObservationCheckError("mumei observe report has no results array")
    return report


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _format_call(result: dict[str, Any], spec: dict) -> str:
    target = str(result.get("target", "<unknown>"))
    args = result.get("args")
    if isinstance(args, dict):
        params_by_name = {
            str(atom.get("name")): [
                str(param.get("name"))
                for param in atom.get("inputs", atom.get("params", []))
                if isinstance(param, dict) and param.get("name")
            ]
            for atom in spec.get("atoms", [])
            if isinstance(atom, dict)
        }
        names = params_by_name.get(target, [])
        values = (
            [args[name] for name in names]
            if names and set(args) == set(names)
            else [args[name] for name in sorted(args)]
        )
    elif isinstance(args, list):
        values = args
    else:
        values = []
    return f"{target}({', '.join(_format_value(value) for value in values)})"


def observation_feedback_parts(
    report: dict,
    spec: dict,
) -> tuple[list[str], list[str]]:
    """Split blocking contract conflicts from retryable missing-atom feedback."""
    results = report.get("results")
    if not isinstance(results, list):
        return [], []
    ordered = sorted(
        (result for result in results if isinstance(result, dict)),
        key=lambda result: (
            str(result.get("file", "")),
            int(result.get("line", 0) or 0),
            str(result.get("test", "")),
            str(result.get("target", "")),
            str(result.get("kind", "")),
        ),
    )
    blocking: list[str] = []
    missing_targets: set[str] = set()
    for result in ordered:
        verdict = result.get("verdict")
        target = str(result.get("target", "<unknown>"))
        if verdict == "not_checked" and result.get("detail") == "no_atom":
            missing_targets.add(target)
            continue
        if verdict not in _BLOCKING_VERDICTS:
            continue
        test = str(result.get("test", "<unknown>"))
        location = f"{result.get('file', '<unknown>')}:{result.get('line', '?')}"
        call = _format_call(result, spec)
        if verdict == "contradicts_ensures":
            if result.get("kind") == "example":
                observed = f"{call} == {_format_value(result.get('result'))}"
            elif result.get("kind") == "relation":
                observed = (
                    f"{call} with relation "
                    f"{result.get('predicate', '<unknown>')}"
                )
            else:
                observed = call
            blocking.append(
                f"test {test} ({location}) observed {observed}, "
                f"but atom {target}'s ensures forbids it"
            )
        else:
            blocking.append(
                f"test {test} ({location}) expects {call} to be rejected, "
                f"but atom {target}'s requires admits it"
            )
    soft = []
    if missing_targets:
        soft.append(
            "No atom in the extracted spec for harvested targets: "
            + ", ".join(sorted(missing_targets))
        )
    return blocking, soft


def observation_feedback(report: dict, spec: dict) -> list[str]:
    """Return deterministic retry feedback for conflicting or missing atoms."""
    blocking, soft = observation_feedback_parts(report, spec)
    return blocking + soft


def observation_summary(report: dict) -> str:
    """Format a one-line count for each observation verdict."""
    results = report.get("results")
    totals = report.get("totals")
    counts = Counter(
        result.get("verdict")
        for result in results
        if isinstance(result, dict)
    ) if isinstance(results, list) else Counter()
    if isinstance(totals, dict):
        for verdict in _VERDICTS:
            if isinstance(totals.get(verdict), int):
                counts[verdict] = totals[verdict]
    return "Observation checks: " + ", ".join(
        f"{verdict}={counts[verdict]}" for verdict in _VERDICTS
    )


def observation_prompt_context(harvest: dict) -> str:
    """Build deterministic extraction context from at most forty observations."""
    observations = harvest.get("observations")
    if not isinstance(observations, list):
        observations = []
    ordered = sorted(
        (item for item in observations if isinstance(item, dict)),
        key=lambda item: (
            str(item.get("file", "")),
            int(item.get("line", 0) or 0),
            str(item.get("kind", "")),
            str(item.get("target", "")),
            str(item.get("test", "")),
        ),
    )[:40]
    lines = [
        "# Observed test behavior",
        "Atoms for tested functions must use the same function name and parameter order.",
        "Ensures must hold for every example and relation; requires must exclude rejected inputs.",
    ]
    for observation in ordered:
        target = str(observation.get("target", "<unknown>"))
        args = observation.get("args")
        if isinstance(args, dict):
            params = _target_params(
                harvest,
                target,
                _language_for_observation(observation),
            )
            names = (
                params
                if params is not None and set(params) == set(args)
                else sorted(args)
            )
            values = [args[name] for name in names]
        elif isinstance(args, list):
            values = args
        else:
            values = []
        call = f"{target}({', '.join(_format_value(value) for value in values)})"
        kind = observation.get("kind")
        if kind == "example":
            text = f"{call} == {_format_value(observation.get('result'))}"
        elif kind == "relation":
            text = f"{target}(x…) with {observation.get('predicate', '<unknown>')}"
        elif kind == "rejects":
            text = f"{target}(…) is rejected"
        else:
            continue
        lines.append(
            f"- {text}; args: {_format_value(args)} "
            f"({observation.get('test', '<unknown>')} "
            f"{observation.get('file', '<unknown>')}:{observation.get('line', '?')})"
        )
    return "\n".join(lines)
