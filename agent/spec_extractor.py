"""Natural-language to forge task spec extraction."""
from __future__ import annotations

import ast
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from openai import OpenAI

from agent.config import AgentConfig
from agent.metrics import Metrics
from agent.mumei_client import MumeiClient
from agent.prompts.spec_extraction import (
    SPEC_EXTRACTION_SYSTEM_PROMPT,
    build_extraction_prompt,
)
from agent.generate import _normalize_forge_task_spec
from agent.strategies.generate_strategy import generate_code
from agent.strategies.spec_refinement import run_refinement_loop

logger = logging.getLogger(__name__)

_ATOM_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _json_object_candidate(raw: str) -> str:
    """Extract the most likely JSON object payload from an LLM response."""
    json_match = re.search(r"```(?:json)?\s*\n(.*?)```", raw, re.DOTALL)
    if json_match:
        return json_match.group(1).strip()

    text = raw.strip()
    start = text.find("{")
    if start < 0:
        return text
    end = text.rfind("}")
    if end >= start:
        return text[start:end + 1].strip()
    return text[start:].strip()


def _strip_json_comments(text: str) -> str:
    """Remove JSON-like comment lines and inline comments outside strings."""
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("//") or stripped.startswith("#"):
            continue
        lines.append(_strip_inline_json_comment(line))
    return "\n".join(lines).strip()


def _strip_inline_json_comment(line: str) -> str:
    quote = ""
    escaped = False
    output: list[str] = []
    index = 0
    while index < len(line):
        char = line[index]
        if quote:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            index += 1
            continue

        if char in {"'", '"'}:
            quote = char
            output.append(char)
            index += 1
            continue
        if char == "#" or (char == "/" and index + 1 < len(line) and line[index + 1] == "/"):
            break
        output.append(char)
        index += 1
    return "".join(output).rstrip()


def _remove_trailing_commas(text: str) -> str:
    return re.sub(r",\s*([}\]])", r"\1", text)


def _complete_json_closers(text: str) -> str:
    stack: list[str] = []
    quote = ""
    escaped = False
    open_to_close = {"{": "}", "[": "]"}
    close_to_open = {"}": "{", "]": "["}

    for char in text:
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in {"'", '"'}:
            quote = char
        elif char in open_to_close:
            stack.append(char)
        elif char in close_to_open and stack and stack[-1] == close_to_open[char]:
            stack.pop()

    return text.rstrip() + "".join(open_to_close[char] for char in reversed(stack))


def _single_quoted_json_to_double(text: str) -> str:
    output: list[str] = []
    quote = ""
    escaped = False
    for char in text:
        if quote == "'":
            if escaped:
                output.append(char)
                escaped = False
            elif char == "\\":
                output.append(char)
                escaped = True
            elif char == "'":
                output.append('"')
                quote = ""
            elif char == '"':
                output.append('\\"')
            else:
                output.append(char)
            continue
        if quote == '"':
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quote = ""
            continue
        if char == "'":
            output.append('"')
            quote = "'"
        else:
            if char == '"':
                quote = '"'
            output.append(char)
    return "".join(output)


def _json_repair_candidates(json_str: str) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    def add(candidate: str) -> None:
        candidate = candidate.strip()
        if candidate and candidate not in seen:
            seen.add(candidate)
            candidates.append(candidate)

    add(json_str)
    for base in (json_str, _strip_json_comments(json_str)):
        add(base)
        no_trailing = _remove_trailing_commas(base)
        add(no_trailing)
        add(_complete_json_closers(no_trailing))
        single_repaired = _single_quoted_json_to_double(no_trailing)
        add(single_repaired)
        add(_complete_json_closers(single_repaired))
    return candidates


def _parse_json_candidate(candidate: str) -> object:
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    try:
        return ast.literal_eval(candidate)
    except (SyntaxError, ValueError):
        return json.loads(candidate)


def _extract_json(raw: str) -> dict:
    """Parse and repair a JSON object from a raw LLM response."""
    json_str = _json_object_candidate(raw)
    last_error: Exception | None = None
    for candidate in _json_repair_candidates(json_str):
        try:
            parsed = _parse_json_candidate(candidate)
        except (json.JSONDecodeError, ValueError, SyntaxError) as exc:
            last_error = exc
            continue
        if not isinstance(parsed, dict):
            raise ValueError("extracted JSON must be an object")
        return parsed
    if last_error is not None:
        raise last_error
    raise ValueError("extracted JSON must be non-empty")


def _catalog_to_prompt_text(catalog: Any) -> str:
    """Convert a catalog payload into compact prompt context."""
    if catalog in (None, "", {}, []):
        return ""
    if isinstance(catalog, str):
        return catalog
    try:
        return json.dumps(catalog, indent=2, ensure_ascii=False)
    except TypeError:
        return str(catalog)


def _load_existing_catalog(mumei_client: MumeiClient | None) -> str:
    """Read std catalog context from an MCP-capable mumei client if available.

    Falls back to scanning std/ directory for atom names when MCP is unavailable.
    """
    if mumei_client is None:
        return ""
    if hasattr(mumei_client, "list_catalog"):
        try:
            catalog = mumei_client.list_catalog()  # type: ignore[attr-defined]
            return _catalog_to_prompt_text(catalog)
        except Exception as exc:
            logger.warning("failed to load std catalog via MCP: %s", exc)
    return _scan_std_catalog_local(mumei_client)


def _scan_std_catalog_local(mumei_client: MumeiClient) -> str:
    """Scan std/ directory for atom names as a catalog fallback."""
    mumei_bin = getattr(mumei_client, "mumei_bin", None) or ""
    mumei_repo = os.environ.get("MUMEI_REPO", "")
    if not mumei_repo and mumei_bin:
        path = Path(mumei_bin)
        if path.name == "mumei" and len(path.parents) >= 3:
            candidate = path.parents[2]
            if (candidate / "std").exists():
                mumei_repo = str(candidate)
    if not mumei_repo:
        return ""
    std_dir = Path(mumei_repo) / "std"
    if not std_dir.exists():
        return ""

    atom_re = re.compile(r"^\s*(?:trusted\s+)?atom\s+(\w+)")
    catalog_lines = []
    for mm_file in sorted(std_dir.rglob("*.mm")):
        rel = str(mm_file.relative_to(std_dir.parent))
        atoms = []
        try:
            for line in mm_file.read_text(encoding="utf-8").splitlines():
                match = atom_re.match(line)
                if match:
                    atoms.append(match.group(1))
        except OSError:
            continue
        if atoms:
            catalog_lines.append(f"- {rel}: {', '.join(atoms)}")
    return "\n".join(catalog_lines) if catalog_lines else ""


def _validate_extracted_spec(spec: dict) -> list[str]:
    """Validate an extracted spec against the forge task spec schema.

    Returns:
        A list of validation error messages (empty if valid).
    """
    errors: list[str] = []
    if not isinstance(spec.get("task_id"), str) or not spec.get("task_id", "").strip():
        errors.append("task_id must be a non-empty string")

    target_file = spec.get("target_file")
    if not isinstance(target_file, str) or not target_file.startswith("std/"):
        errors.append('target_file must be a string starting with "std/"')
    elif (
        Path(target_file).is_absolute()
        or ".." in Path(target_file).parts
        or not target_file.endswith(".mm")
    ):
        errors.append('target_file must be a safe relative std/*.mm path')

    if spec.get("mode") not in {"append", "create", "replace"}:
        errors.append('mode must be one of "append", "create", or "replace"')

    priority = spec.get("priority")
    if priority is not None and (not isinstance(priority, int) or isinstance(priority, bool)):
        errors.append("priority must be an integer when present")
    max_retries = spec.get("max_retries")
    if max_retries is not None and (
        not isinstance(max_retries, int) or isinstance(max_retries, bool) or max_retries <= 0
    ):
        errors.append("max_retries must be a positive integer when present")
    auto_commit = spec.get("auto_commit")
    if auto_commit is not None and not isinstance(auto_commit, bool):
        errors.append("auto_commit must be a boolean when present")

    atoms = spec.get("atoms")
    if not isinstance(atoms, list) or not atoms:
        errors.append("atoms must be a non-empty list")
        return errors

    seen_atom_names: set[str] = set()
    for index, atom in enumerate(atoms):
        prefix = f"atoms[{index}]"
        if not isinstance(atom, dict):
            errors.append(f"{prefix} must be an object")
            continue

        for field in ("name", "description", "return_type", "requires", "ensures"):
            value = atom.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{prefix}.{field} must be a non-empty string")
        name = atom.get("name")
        if isinstance(name, str) and name.strip():
            if not _ATOM_NAME_RE.match(name):
                errors.append(f"{prefix}.name must match [A-Za-z_][A-Za-z0-9_]*")
            if name in seen_atom_names:
                errors.append(f"{prefix}.name must be unique within atoms")
            seen_atom_names.add(name)

        inputs_key = "inputs" if "inputs" in atom else "params"
        inputs = atom.get(inputs_key)
        if not isinstance(inputs, list):
            errors.append(f"{prefix}.inputs must be a list")
        else:
            for input_index, item in enumerate(inputs):
                item_prefix = f"{prefix}.{inputs_key}[{input_index}]"
                if not isinstance(item, dict):
                    errors.append(f"{item_prefix} must be an object")
                    continue
                for field in ("name", "type"):
                    value = item.get(field)
                    if not isinstance(value, str) or not value.strip():
                        errors.append(f"{item_prefix}.{field} must be a non-empty string")

        effects = atom.get("effects")
        if not isinstance(effects, list):
            errors.append(f"{prefix}.effects must be a list")
        elif not all(isinstance(effect, str) and effect.strip() for effect in effects):
            errors.append(f"{prefix}.effects entries must be non-empty strings")

        reference_patterns = atom.get("reference_patterns")
        if reference_patterns is not None and (
            not isinstance(reference_patterns, list)
            or not all(isinstance(pattern, str) and pattern.strip() for pattern in reference_patterns)
        ):
            errors.append(f"{prefix}.reference_patterns must be a list of non-empty strings")
    return errors


def validate_forge_task_spec(spec: dict) -> None:
    """Raise ``ValueError`` if *spec* is not a valid forge task spec."""
    errors = _validate_extracted_spec(spec)
    if errors:
        raise ValueError("invalid forge task spec: " + "; ".join(errors))


def _matches_requirement_trigger(trigger: str, lowered_prompt: str) -> bool:
    if trigger.isascii():
        pattern = rf"(?<![a-z0-9_]){re.escape(trigger)}(?![a-z0-9_])"
        return re.search(pattern, lowered_prompt) is not None
    return trigger in lowered_prompt


def _keyword_validation_errors(spec: dict, natural_language: str) -> list[str]:
    """Return errors when extraction obviously copied the schema example."""
    lowered_prompt = natural_language.lower()
    spec_text = json.dumps(spec, ensure_ascii=False).lower()
    keyword_groups = [
        ("銀行", ("transfer", "balance", "amount", "送金", "残高")),
        ("送金", ("transfer", "balance", "amount", "送金", "残高")),
        ("kyc", ("kyc", "risk", "pep", "customer", "顧客")),
        ("pep", ("kyc", "risk", "pep", "customer", "顧客")),
        ("aml", ("aml", "risk", "sanction", "customer", "kyc")),
        ("queue", ("queue", "enqueue", "dequeue", "capacity", "length")),
        ("list", ("list", "index", "length", "bounds", "capacity")),
        ("overflow", ("overflow", "bounded", "max", "min", "安全")),
        ("絶対値", ("abs", "absolute", "non-negative", "非負")),
    ]
    errors = []
    for trigger, expected_keywords in keyword_groups:
        if _matches_requirement_trigger(trigger, lowered_prompt) and not any(
            keyword in spec_text for keyword in expected_keywords
        ):
            errors.append(
                f"spec does not reflect requirement keyword {trigger!r}; "
                "do not copy the schema example"
            )
    return errors


_RETRY_FEEDBACK_RAW_LIMIT = 2000


def _format_retry_feedback(raw_output: str, errors: list[str]) -> str:
    """Format retry feedback with concrete errors and prior LLM output.

    The previous LLM output is truncated to ``_RETRY_FEEDBACK_RAW_LIMIT``
    characters to avoid unbounded prompt growth across retries (which would
    inflate token usage and risk exceeding context limits).
    """
    truncated = raw_output.strip()
    if len(truncated) > _RETRY_FEEDBACK_RAW_LIMIT:
        truncated = (
            truncated[:_RETRY_FEEDBACK_RAW_LIMIT]
            + f"\n... [truncated, {len(raw_output) - _RETRY_FEEDBACK_RAW_LIMIT} chars omitted]"
        )
    return (
        "Validation errors:\n"
        + "\n".join(f"- {error}" for error in errors)
        + "\n\nPrevious LLM output:\n```\n"
        + truncated
        + "\n```"
    )


def extract_spec(
    client: OpenAI,
    model: str,
    natural_language: str,
    *,
    domain_hint: str = "",
    mumei_client: MumeiClient | None = None,
    max_retries: int = 3,
    metrics: Metrics | None = None,
    detect_ambiguity: bool = False,
    config: AgentConfig | None = None,
) -> dict:
    """Extract a forge task spec from natural language.

    Pipeline:
        1. (Optional) Call mumei MCP server's list_std_catalog() to get existing catalog
        2. Build extraction prompt with natural_language + domain_hint + catalog
        3. Call LLM to generate spec JSON
        4. Validate the output against forge task spec schema
        5. If validation fails, retry with error feedback
        6. Return validated spec dict

    Returns:
        A forge task spec dict compatible with forge_tasks/*.json format.
    """
    if not natural_language.strip():
        raise ValueError("natural_language must be non-empty")

    if detect_ambiguity:
        from agent.ambiguity_detector import AmbiguityDetector

        detector = AmbiguityDetector(config or AgentConfig())
        ambiguity_result = detector.detect_ambiguity(natural_language)
        for warning in ambiguity_result.warnings:
            logger.warning(warning)
        if ambiguity_result.errors:
            raise ValueError("; ".join(ambiguity_result.errors))
        if ambiguity_result.has_ambiguity:
            logger.warning(
                "Ambiguity detected in specification: %d findings",
                len(ambiguity_result.findings),
            )

    existing_catalog = _load_existing_catalog(mumei_client)
    base_prompt = build_extraction_prompt(
        natural_language,
        domain_hint=domain_hint,
        existing_catalog=existing_catalog,
    )
    feedback = ""
    attempts = max(1, max_retries)
    last_errors: list[str] = []

    for attempt in range(1, attempts + 1):
        if metrics is not None:
            metrics.record_extraction_attempt()
        prompt = base_prompt
        if feedback:
            prompt += (
                "\n\n# Previous extraction failed\n"
                f"{feedback}\n"
                "Return a corrected forge task spec JSON object."
            )

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SPEC_EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or ""
        try:
            spec = _extract_json(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            last_errors = [f"invalid JSON: {exc}"]
            feedback = _format_retry_feedback(raw, last_errors)
            continue

        validation_errors = _validate_extracted_spec(spec)
        if not validation_errors:
            validation_errors = _keyword_validation_errors(spec, natural_language)
        if not validation_errors:
            if metrics is not None:
                metrics.record_extraction_success()
            return spec
        last_errors = validation_errors
        feedback = _format_retry_feedback(raw, validation_errors)

    raise ValueError(
        f"failed to extract valid forge task spec after {attempts} attempts: "
        + "; ".join(last_errors)
    )


def extract_and_generate(
    client: OpenAI,
    model: str,
    natural_language: str,
    *,
    domain_hint: str = "",
    mumei_client: MumeiClient | None = None,
    max_extraction_retries: int = 3,
    max_generation_retries: int = 5,
    max_refinements: int = 3,
) -> tuple[str, bool, dict]:
    """Full pipeline: natural language → spec → verified code.

    Combines extract_spec() with the existing generate_code() and
    run_refinement_loop() from spec_refinement.py.

    Returns:
        A tuple of (code, verified, final_spec).
    """
    metrics = Metrics()
    spec = extract_spec(
        client,
        model,
        natural_language,
        domain_hint=domain_hint,
        mumei_client=mumei_client,
        max_retries=max_extraction_retries,
        metrics=metrics,
    )
    return run_refinement_loop(
        client,
        model,
        _normalize_forge_task_spec(spec),
        generate_code,
        max_refinements=max_refinements,
        config_max_retries=max_generation_retries,
        mumei_client=mumei_client,
        metrics=metrics,
    )
