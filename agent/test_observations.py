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
    "domain_exceeds_requires",
    "entailed",
    "inconclusive",
    "not_checked",
    "not_entailed",
    "outside_requires",
    "rejection_explained",
    "requires_admits_rejected",
)
_BLOCKING_VERDICTS = {"contradicts_ensures", "requires_admits_rejected"}
_PROPERTY_VERDICTS = {
    "entailed",
    "not_entailed",
    "contradicts_ensures",
    "domain_exceeds_requires",
    "outside_requires",
    "inconclusive",
    "not_checked",
}


class ObservationCheckError(ValueError):
    """Raised when mumei cannot produce a valid observation-check report."""


def _spec_atoms(spec: dict) -> list[Any]:
    atoms = spec.get("atoms")
    if isinstance(atoms, list):
        return atoms
    if (
        "atoms" not in spec
        and spec.get("name")
        and ("requires" in spec or "ensures" in spec)
        and ("inputs" in spec or "params" in spec)
    ):
        return [spec]
    return []


def spec_to_observe_module(spec: dict) -> str:
    """Render trusted atoms with the extracted spec's real signatures."""
    normalized = dict(spec)
    normalized["atoms"] = _spec_atoms(spec)
    return _spec_to_contradiction_check_module(normalized)


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


def _format_arg_value(value: Any) -> str:
    if (
        isinstance(value, dict)
        and len(value) == 1
        and isinstance(value.get("var"), str)
    ):
        return value["var"]
    return _format_value(value)


def _format_variable(variable: Any) -> str | None:
    if not isinstance(variable, dict) or not isinstance(variable.get("name"), str):
        return None
    name = variable["name"]
    if variable.get("type") == "bool":
        return f"{name}: bool"
    has_min = "min" in variable
    has_max = "max" in variable
    if has_min and has_max:
        return (
            f"{name} in [{_format_value(variable['min'])}, "
            f"{_format_value(variable['max'])}]"
        )
    if has_min:
        return f"{name} >= {_format_value(variable['min'])}"
    if has_max:
        return f"{name} <= {_format_value(variable['max'])}"
    variable_type = variable.get("type")
    if not isinstance(variable_type, str) or not variable_type:
        variable_type = "i64"
    return f"{name}: {variable_type}"


def _format_property_call(
    target: str,
    args: Any,
    param_names: list[str] | None,
) -> str:
    if isinstance(args, dict):
        names = (
            param_names
            if param_names is not None and set(args) == set(param_names)
            else sorted(args)
        )
        values = [f"{name}={_format_arg_value(args[name])}" for name in names]
    elif isinstance(args, list):
        if param_names is not None and len(args) == len(param_names):
            values = [
                f"{name}={_format_arg_value(value)}"
                for name, value in zip(param_names, args)
            ]
        else:
            values = [_format_arg_value(value) for value in args]
    else:
        values = []
    return f"{target}({', '.join(values)})"


def _format_property(
    call: str,
    variables: list[Any] | None,
    assumptions: list[Any] | None,
    predicate: Any,
) -> str:
    formatted_variables = (
        [text for variable in variables if (text := _format_variable(variable))]
        if isinstance(variables, list)
        else []
    )
    formatted_assumptions = (
        [item for item in assumptions if isinstance(item, str) and item]
        if isinstance(assumptions, list)
        else []
    )
    if formatted_variables and assumptions is not None:
        quantified = ", ".join(formatted_variables)
    else:
        quantified = "generated inputs"
    text = f"for all {quantified}"
    if formatted_assumptions:
        text += f", assuming {' && '.join(formatted_assumptions)}"
    if not isinstance(predicate, str) or not predicate:
        predicate = "<unknown>"
    return f"{text}: {call} satisfies {predicate}"


def _spec_param_names(spec: dict, target: str) -> list[str] | None:
    for atom in _spec_atoms(spec):
        if not isinstance(atom, dict) or str(atom.get("name")) != target:
            continue
        params = atom.get("inputs", atom.get("params", []))
        if not isinstance(params, list):
            return []
        return [
            str(param.get("name"))
            for param in params
            if isinstance(param, dict) and param.get("name")
        ]
    return []


def _format_call(result: dict[str, Any], spec: dict) -> str:
    target = str(result.get("target", "<unknown>"))
    args = result.get("args")
    if isinstance(args, dict):
        names = _spec_param_names(spec, target) or []
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


def _property_metadata(
    result: dict[str, Any],
    harvest: dict | None,
) -> tuple[list[Any] | None, list[Any] | None]:
    variables = result.get("variables")
    assumptions = result.get("assumptions")
    if isinstance(variables, list) and isinstance(assumptions, list):
        return variables, assumptions
    observations = harvest.get("observations") if isinstance(harvest, dict) else None
    if not isinstance(observations, list):
        return (
            variables if isinstance(variables, list) else None,
            assumptions if isinstance(assumptions, list) else None,
        )
    match_fields = ("file", "line", "test", "target", "predicate")
    candidates = [
        observation
        for observation in observations
        if isinstance(observation, dict)
        and observation.get("kind") == "property"
        and all(observation.get(field) == result.get(field) for field in match_fields)
    ]
    if len(candidates) > 1:
        candidates = [
            observation
            for observation in candidates
            if observation.get("args") == result.get("args")
        ]
    if not candidates:
        return (
            variables if isinstance(variables, list) else None,
            assumptions if isinstance(assumptions, list) else None,
        )
    first_variables = candidates[0].get("variables")
    first_assumptions = candidates[0].get("assumptions")
    if any(
        candidate.get("variables") != first_variables
        or candidate.get("assumptions") != first_assumptions
        for candidate in candidates[1:]
    ):
        return None, None
    return (
        variables if isinstance(variables, list) else first_variables,
        assumptions if isinstance(assumptions, list) else first_assumptions,
    )


def _ordered_results(report: dict) -> list[dict[str, Any]]:
    results = report.get("results")
    if not isinstance(results, list):
        return []
    return sorted(
        (result for result in results if isinstance(result, dict)),
        key=lambda result: (
            str(result.get("file", "")),
            int(result.get("line", 0) or 0),
            str(result.get("test", "")),
            str(result.get("target", "")),
            str(result.get("kind", "")),
        ),
    )


def _observation_location(result: dict[str, Any]) -> tuple[str, str]:
    test = str(result.get("test", "<unknown>"))
    location = f"{result.get('file', '<unknown>')}:{result.get('line', '?')}"
    return test, location


def _property_quantified(
    result: dict[str, Any],
    spec: dict,
    harvest: dict | None,
) -> str:
    target = str(result.get("target", "<unknown>"))
    variables, assumptions = _property_metadata(result, harvest)
    call = _format_property_call(
        target,
        result.get("args"),
        _spec_param_names(spec, target),
    )
    return _format_property(
        call,
        variables,
        assumptions,
        result.get("predicate"),
    )


def _counterexample_suffix(result: dict[str, Any]) -> str:
    detail = result.get("detail")
    return f" (counterexample: {detail})" if isinstance(detail, str) and detail else ""


def observation_feedback_parts(
    report: dict,
    spec: dict,
    harvest: dict | None = None,
) -> tuple[list[str], list[str]]:
    """Split blocking contract conflicts from retryable feedback."""
    ordered = _ordered_results(report)
    blocking: list[str] = []
    not_entailed: list[str] = []
    missing_targets: set[str] = set()
    for result in ordered:
        verdict = result.get("verdict")
        target = str(result.get("target", "<unknown>"))
        if verdict == "not_checked" and result.get("detail") == "no_atom":
            missing_targets.add(target)
            continue
        if result.get("kind") == "property":
            test, location = _observation_location(result)
            quantified = _property_quantified(result, spec, harvest)
            if verdict == "contradicts_ensures":
                blocking.append(
                    f"test {test} ({location}) checks {quantified}, but atom "
                    f"{target}'s ensures contradict the predicate for every "
                    "generated input that requires admits"
                )
            elif verdict == "requires_admits_rejected":
                blocking.append(
                    f"test {test} ({location}) got verdict "
                    f"requires_admits_rejected for property {quantified}, "
                    "which is not a property verdict"
                )
            elif verdict == "not_entailed":
                predicate = result.get("predicate")
                if not isinstance(predicate, str) or not predicate:
                    predicate = "<unknown>"
                not_entailed.append(
                    f"test {test} ({location}) checks {quantified}, but atom "
                    f"{target}'s ensures do not guarantee it; strengthen "
                    f"ensures so that {predicate} holds whenever requires and "
                    f"the test's assumptions hold"
                    f"{_counterexample_suffix(result)}"
                )
            continue
        if verdict not in _BLOCKING_VERDICTS:
            continue
        test, location = _observation_location(result)
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
    soft = list(not_entailed)
    if missing_targets:
        soft.append(
            "No atom in the extracted spec for harvested targets: "
            + ", ".join(sorted(missing_targets))
        )
    return blocking, soft


def observation_feedback(
    report: dict,
    spec: dict,
    harvest: dict | None = None,
) -> list[str]:
    """Return deterministic retry feedback for conflicting or missing atoms."""
    blocking, soft = observation_feedback_parts(report, spec, harvest)
    return blocking + soft


def observation_summary(report: dict) -> str:
    """Format a one-line count for each observation verdict."""
    results = report.get("results")
    totals = report.get("totals")
    counts = Counter(
        result.get("verdict")
        for result in results
        if isinstance(result, dict) and result.get("verdict") in _VERDICTS
    ) if isinstance(results, list) else Counter()
    if isinstance(totals, dict):
        for verdict in _VERDICTS:
            if isinstance(totals.get(verdict), int):
                counts[verdict] = totals[verdict]
    summary = "Observation checks: " + ", ".join(
        f"{verdict}={counts[verdict]}" for verdict in _VERDICTS
    )
    unrecognized = sum(
        1
        for result in results
        if isinstance(result, dict) and result.get("verdict") not in _VERDICTS
    ) if isinstance(results, list) else 0
    if unrecognized:
        summary += f", unrecognized={unrecognized}"
    return summary


def observation_warnings(
    report: dict,
    spec: dict,
    harvest: dict | None = None,
) -> list[str]:
    """Return stable warnings for unchecked and non-failing property results."""
    warnings = []
    for result in _ordered_results(report):
        verdict = result.get("verdict")
        test, location = _observation_location(result)
        if verdict not in _VERDICTS:
            warnings.append(
                f"test {test} ({location}) got unrecognized verdict "
                f"{verdict!r} from mumei observe; treating it as unchecked"
            )
            continue
        if result.get("kind") != "property":
            continue
        target = str(result.get("target", "<unknown>"))
        quantified = _property_quantified(result, spec, harvest)
        if verdict == "not_entailed":
            warnings.append(
                f"test {test} ({location}): atom {target}'s ensures do not "
                f"guarantee {quantified}{_counterexample_suffix(result)}"
            )
        elif verdict == "domain_exceeds_requires":
            warnings.append(
                f"test {test} ({location}) generates inputs outside atom "
                f"{target}'s requires for {quantified}; the predicate holds "
                "where requires admits the input"
            )
        elif verdict == "outside_requires":
            warnings.append(
                f"no input generated by test {test} ({location}) for "
                f"{quantified} satisfies atom {target}'s requires"
            )
        elif verdict == "inconclusive":
            detail = result.get("detail")
            suffix = f": {detail}" if detail else ""
            warnings.append(
                f"could not decide test {test} ({location}) for "
                f"{quantified}{suffix}"
            )
        elif verdict == "not_checked":
            detail = result.get("detail")
            if detail != "no_atom":
                detail_text = detail if detail else "no detail"
                suffix = (
                    "; this mumei build does not support property observations"
                    if detail == "unsupported observation kind"
                    else ""
                )
                warnings.append(
                    f"property test {test} ({location}) was not checked: "
                    f"{detail_text}{suffix}"
                )
        elif verdict not in _PROPERTY_VERDICTS and verdict not in _BLOCKING_VERDICTS:
            warnings.append(
                f"test {test} ({location}) got verdict {verdict} for property "
                f"{quantified}, which is not a property verdict; treating it "
                "as unchecked"
            )
    return warnings


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
    has_property = any(item.get("kind") == "property" for item in ordered)
    if has_property:
        lines.append(
            "Ensures must imply every property predicate for all inputs in the "
            "stated ranges that satisfy the assumptions and requires."
        )
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
        elif kind == "property":
            text = _format_property(
                _format_property_call(
                    target,
                    args,
                    _target_params(
                        harvest,
                        target,
                        _language_for_observation(observation),
                    ),
                ),
                observation.get("variables"),
                observation.get("assumptions"),
                observation.get("predicate"),
            )
            lines.append(
                f"- {observation.get('test', '<unknown>')} "
                f"({observation.get('file', '<unknown>')}:"
                f"{observation.get('line', '?')}): {text}"
            )
            continue
        else:
            continue
        lines.append(
            f"- {text}; args: {_format_value(args)} "
            f"({observation.get('test', '<unknown>')} "
            f"{observation.get('file', '<unknown>')}:{observation.get('line', '?')})"
        )
    return "\n".join(lines)
