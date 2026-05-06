"""Natural-language to forge task spec extraction."""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from openai import OpenAI

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


def _extract_json(raw: str) -> dict:
    """Parse a JSON object from a raw LLM response."""
    json_match = re.search(r"```(?:json)?\s*\n(.*?)```", raw, re.DOTALL)
    json_str = json_match.group(1).strip() if json_match else raw.strip()
    parsed = json.loads(json_str)
    if not isinstance(parsed, dict):
        raise ValueError("extracted JSON must be an object")
    return parsed


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

    Checks:
    - task_id exists and is a string
    - target_file exists and starts with "std/"
    - mode is one of "append", "create", "replace"
    - atoms is a non-empty list
    - Each atom has name, inputs (list of {name, type}), return_type, requires, ensures
    - requires and ensures are non-empty strings

    Returns:
        A list of validation error messages (empty if valid).
    """
    errors: list[str] = []
    if not isinstance(spec.get("task_id"), str) or not spec.get("task_id", "").strip():
        errors.append("task_id must be a non-empty string")
    target_file = spec.get("target_file")
    if not isinstance(target_file, str) or not target_file.startswith("std/"):
        errors.append('target_file must be a string starting with "std/"')
    if spec.get("mode") not in {"append", "create", "replace"}:
        errors.append('mode must be one of "append", "create", or "replace"')

    atoms = spec.get("atoms")
    if not isinstance(atoms, list) or not atoms:
        errors.append("atoms must be a non-empty list")
        return errors

    for index, atom in enumerate(atoms):
        prefix = f"atoms[{index}]"
        if not isinstance(atom, dict):
            errors.append(f"{prefix} must be an object")
            continue
        for field in ("name", "return_type", "requires", "ensures"):
            value = atom.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{prefix}.{field} must be a non-empty string")
        inputs = atom.get("inputs", atom.get("params"))
        if not isinstance(inputs, list):
            errors.append(f"{prefix}.inputs must be a list")
        else:
            for input_index, item in enumerate(inputs):
                item_prefix = f"{prefix}.inputs[{input_index}]"
                if not isinstance(item, dict):
                    errors.append(f"{item_prefix} must be an object")
                    continue
                for field in ("name", "type"):
                    value = item.get(field)
                    if not isinstance(value, str) or not value.strip():
                        errors.append(f"{item_prefix}.{field} must be a non-empty string")
    return errors


def _keyword_validation_errors(spec: dict, natural_language: str) -> list[str]:
    """Return errors when extraction obviously copied the schema example."""
    lowered_prompt = natural_language.lower()
    spec_text = json.dumps(spec, ensure_ascii=False).lower()
    keyword_groups = [
        ("銀行", ("transfer", "balance", "amount", "送金", "残高")),
        ("送金", ("transfer", "balance", "amount", "送金", "残高")),
        ("kyc", ("kyc", "risk", "pep", "customer", "顧客")),
        ("pep", ("kyc", "risk", "pep", "customer", "顧客")),
        ("絶対値", ("abs", "absolute", "non-negative", "非負")),
    ]
    errors = []
    for trigger, expected_keywords in keyword_groups:
        if trigger in lowered_prompt and not any(
            keyword in spec_text for keyword in expected_keywords
        ):
            errors.append(
                f"spec does not reflect requirement keyword {trigger!r}; "
                "do not copy the schema example"
            )
    return errors


def extract_spec(
    client: OpenAI,
    model: str,
    natural_language: str,
    *,
    domain_hint: str = "",
    mumei_client: MumeiClient | None = None,
    max_retries: int = 3,
    metrics: Metrics | None = None,
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
            feedback = "; ".join(last_errors)
            continue

        validation_errors = _validate_extracted_spec(spec)
        if not validation_errors:
            validation_errors = _keyword_validation_errors(spec, natural_language)
        if not validation_errors:
            if metrics is not None:
                metrics.record_extraction_success()
            return spec
        last_errors = validation_errors
        feedback = "; ".join(validation_errors)

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
