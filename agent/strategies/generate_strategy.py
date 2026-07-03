"""Generate strategy: generate -> verify -> fix pipeline."""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

from openai import OpenAI

from agent.llm_provider import complete_text
from agent.mumei_client import MumeiClient
from agent.metrics import Metrics
from agent.prompts.report_formatter import (
    format_error_diff,
    format_retry_report_context,
    is_contextual_suggestion,
)
from agent.spec_code_mapper import SpecCodeMapper
from agent.thought_log import (
    ThoughtProcess,
    describe_fix,
    summarize_code_diff,
    summarize_z3_result,
)
from agent.strategies.generate_strategy_prompt import (
    _ATOM_SIGNATURE_RE,
    _CORE_AXIOM_CACHE,
    _CORE_AXIOM_HEADER,
    _TYPE_DEFINITION_RE,
    _build_core_axiom_context,
    _build_multi_atom_prompt,
    _build_skeleton,
    _default_prompt_report_truncate_chars,
    _detect_dependencies,
    _extract_code,
    _has_effects,
    _identify_failing_atoms,
    _is_std_module,
    _load_core_axiom_context,
    _select_prompt_module,
    _summarise_core_axioms,
)

if TYPE_CHECKING:
    from agent.config import AgentConfig

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Phase 2-B — std/core.mm core-axiom injection for std/ module generation
# ---------------------------------------------------------------------------

# Sentinel used by prompt assemblers to recognise a previously-injected
# core-axiom block and avoid duplicating it.

# Regex that captures ``type ... ;`` and ``atom NAME(...) requires: ...;
# ensures: ...;`` signatures.  Bodies (``body: { ... };``) are
# intentionally stripped so the prompt stays token-efficient.

























def _spec_code_mapping_payload(
    spec: dict,
    code: str,
    verification_report: dict | None = None,
    *,
    enabled: bool = True,
) -> list[dict]:
    if not enabled:
        return []
    mapper = SpecCodeMapper()
    result = mapper.build_mapping(spec, code, verification_report)
    return mapper.to_json(result.mappings)


def _verify_with_spec_code_mapping(
    mumei_client: MumeiClient,
    source_path: str,
    spec: dict,
    code: str,
    *,
    enabled: bool = True,
) -> dict:
    mapping = _spec_code_mapping_payload(spec, code, enabled=enabled)
    try:
        if enabled:
            verify_result = mumei_client.verify(source_path, spec_code_mapping=mapping)
        else:
            verify_result = mumei_client.verify(source_path)
    except TypeError:
        verify_result = mumei_client.verify(source_path)
    report = verify_result.get("report") or {}
    if isinstance(report, dict):
        mapping = _spec_code_mapping_payload(spec, code, report, enabled=enabled)
        if enabled:
            report["spec_code_mapping"] = mapping
        verify_result["report"] = report
    if enabled:
        verify_result["spec_code_mapping"] = mapping
    return verify_result


def _verify_with_metrics(
    mumei_client: MumeiClient,
    source_path: str,
    spec: dict,
    code: str,
    metrics: Metrics | None,
    *,
    dense_properties: bool,
    enabled: bool = True,
) -> dict:
    start = time.perf_counter()
    verify_result = _verify_with_spec_code_mapping(
        mumei_client,
        source_path,
        spec,
        code,
        enabled=enabled,
    )
    if metrics is not None:
        metrics.record_verification_time(time.perf_counter() - start, dense_properties)
    return verify_result


def _time_verify_candidate(
    mumei_client: MumeiClient,
    code: str,
    spec: dict,
    *,
    enabled: bool = True,
) -> tuple[dict, float]:
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".mm", delete=False, encoding="utf-8"
        ) as tmp:
            tmp_path = tmp.name
            tmp.write(code)
        start = time.perf_counter()
        verify_result = _verify_with_spec_code_mapping(
            mumei_client,
            tmp_path,
            spec,
            code,
            enabled=enabled,
        )
        return verify_result, time.perf_counter() - start
    finally:
        try:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass


def _load_generation_config(spec: dict) -> AgentConfig | None:
    """Return an AgentConfig for generation-scoped feature flags."""
    try:
        from agent.config import AgentConfig
    except ImportError:  # pragma: no cover - defensive
        return None

    config = spec.get("_agent_config")
    if isinstance(config, AgentConfig):
        if not hasattr(config, "enable_generation_health_check"):
            config.enable_generation_health_check = True
        if not hasattr(config, "enable_dense_properties"):
            config.enable_dense_properties = False
        return config
    try:
        return AgentConfig()
    except Exception:
        return None


def _health_check_generated_code(
    spec_json: str,
    generated_code: str,
    model: str,
    config: AgentConfig | None,
    past_code_examples: list[str],
    *,
    track_example: bool = True,
) -> bool:
    if config is None or not config.enable_generation_health_check:
        if track_example:
            past_code_examples.append(generated_code)
        return True

    from agent.generation_health_checker import GenerationHealthChecker

    checker = GenerationHealthChecker(config)
    for past_code in past_code_examples:
        checker.add_past_example(past_code)

    result = checker.check_generation_health(
        spec_json,
        generated_code,
        generation_metadata={"model": model},
    )
    if track_example:
        past_code_examples.append(generated_code)
    if result.is_healthy:
        return True

    _logger.warning(
        "Generation health check failed: warnings=%s errors=%s",
        result.warnings,
        result.errors,
    )
    return False


def _retry_for_health(
    client: OpenAI,
    model: str,
    prompt: str,
    system_content: str,
    spec_for_json: dict,
    enable_dense_properties: bool,
    metrics: Metrics | None = None,
) -> str:
    retry_code = _regenerate_for_health(
        client,
        model,
        prompt,
        system_content,
        "low spec adherence or low code diversity",
    )
    if retry_code and enable_dense_properties:
        retry_code = _try_apply_dense_properties(
            retry_code,
            spec_for_json,
            client,
            model,
            metrics,
        )
    return retry_code


def _regenerate_unhealthy_code(
    client: OpenAI,
    model: str,
    prompt: str,
    system_content: str,
    spec_json: str,
    generated_code: str,
    config: AgentConfig | None,
    past_code_examples: list[str],
    spec_for_json: dict,
    enable_dense_properties: bool,
    metrics: Metrics | None = None,
) -> str:
    if _health_check_generated_code(
        spec_json,
        generated_code,
        model,
        config,
        past_code_examples,
        track_example=False,
    ):
        return generated_code

    retry_code = _retry_for_health(
        client,
        model,
        prompt,
        system_content,
        spec_for_json,
        enable_dense_properties,
        metrics,
    )
    if not retry_code:
        return generated_code

    _health_check_generated_code(
        spec_json, retry_code, model, config, past_code_examples,
    )
    return retry_code


def _regenerate_for_health(
    client: OpenAI,
    model: str,
    prompt: str,
    system_content: str,
    health_warnings: str,
) -> str:
    retry_prompt = (
        f"{prompt}\n\n"
        "# Generation Health Retry\n"
        "The previous generation did not sufficiently reflect the current specification "
        "or was too similar to prior examples. Regenerate from the specification, "
        "using the skeleton and current requirements as the source of truth.\n"
        f"Health warnings: {health_warnings}"
    )
    content = complete_text(
        client,
        [
            {"role": "system", "content": system_content},
            {"role": "user", "content": retry_prompt},
        ],
        model,
    )
    return _extract_code(content)


def generate_multi_atom(
    client: OpenAI,
    model: str,
    spec: dict,
    config_max_retries: int = 5,
    mumei_client: MumeiClient | None = None,
    metrics: Metrics | None = None,
    thought_process: ThoughtProcess | None = None,
    enable_dense_properties: bool | None = None,
    enable_spec_code_mapping: bool | None = None,
    prompt_report_truncate_chars: int | None = None,
) -> tuple[str, bool]:
    """Generate a multi-atom Mumei module from a specification.

    Accepts a spec with an ``atoms`` array, generates skeletons for each
    atom (with dependency context), sends them to the LLM as a single
    generation request, then verifies and iteratively fixes.

    Args:
        client: OpenAI-compatible client.
        model: Model name.
        spec: Specification dict with ``module_name`` and ``atoms`` array.
        config_max_retries: Maximum number of fix attempts.
        mumei_client: MumeiClient for running check/verify.
        metrics: Optional Metrics instance for tracking.
        thought_process: Optional ThoughtProcess for explainability.
        enable_dense_properties: When true, generate dense contracts after
            initial code generation.
        enable_spec_code_mapping: When true, attach spec-to-code mapping
            metadata to verification reports.

    Returns:
        A tuple of (code, verified).
    """
    if metrics is None:
        metrics = Metrics()
    generation_config = _load_generation_config(spec)
    past_code_examples: list[str] = []

    if enable_dense_properties is None:
        enable_dense_properties = (
            generation_config.enable_dense_properties
            if generation_config is not None
            else False
        )

    if enable_spec_code_mapping is None:
        try:
            from agent.config import AgentConfig
            enable_spec_code_mapping = AgentConfig().enable_spec_code_mapping
        except Exception:
            enable_spec_code_mapping = True
    if prompt_report_truncate_chars is None:
        prompt_report_truncate_chars = _default_prompt_report_truncate_chars()

    # Extract cross_file_context without mutating the caller's spec dict —
    # ``run_refinement_loop`` (and any other caller) may reuse the same
    # spec for subsequent generate/refine iterations, and losing the
    # context after the first attempt would silently degrade retries.
    cross_file_context = spec.get("cross_file_context")

    # Phase 2-B — always inject std/core.mm axioms when targeting a
    # std/ module so generated atoms reuse Size/Index/NonZero and the
    # safe conversion atoms instead of redefining them.
    core_axiom_context = _build_core_axiom_context(spec)

    # Remove the scratch ``_agent_config`` pointer (if any) before the
    # spec is JSON-serialised into the prompt.
    spec_for_prompt = {k: v for k, v in spec.items() if k != "_agent_config"}

    atoms = spec_for_prompt["atoms"]
    module_name = spec_for_prompt.get("module_name") or "module"
    atom_names = [a["name"] for a in atoms]
    deps = _detect_dependencies(atoms)

    # Build combined skeleton prompt
    combined_skeleton = _build_multi_atom_prompt(atoms, deps)
    # Exclude cross_file_context from the JSON payload so it renders as
    # readable markdown later in the prompt rather than JSON-escaped text.
    spec_for_json = {
        k: v
        for k, v in spec_for_prompt.items()
        if k != "cross_file_context"
    }
    spec_json = json.dumps(spec_for_json, indent=2, ensure_ascii=False)

    # Stage 1: Initial generation
    metrics.record_attempt("generation")
    from agent.prompts import generate_atom as prompt_module

    prompt = prompt_module.build_prompt(spec_json, "", {})
    if core_axiom_context:
        prompt += f"\n\n{core_axiom_context}"
    if cross_file_context:
        prompt += f"\n\n{cross_file_context}"
    prompt += (
        f"\n\n# Multi-atom module '{module_name}' — generate ALL atoms in a single .mm file:\n"
        f"```mumei\n{combined_skeleton}```\n"
        f"\nGenerate a complete .mm file containing all {len(atoms)} atoms. "
        f"Fill in the ___ placeholders with correct logic."
    )

    system_content = (
        "You are a helpful programming assistant specializing "
        "in the Mumei language with its effect system and Z3 formal verification. "
        "Generate a complete module with multiple atoms."
    )
    content = complete_text(
        client,
        [
            {"role": "system", "content": system_content},
            {"role": "user", "content": prompt},
        ],
        model,
    )

    generated_code = _extract_code(content)
    if not generated_code:
        _logger.warning("LLM returned empty multi-atom generation result")
        return "", False

    dense_properties_applied = False
    if enable_dense_properties:
        original_code = generated_code
        generated_code = _try_apply_dense_properties(
            generated_code,
            spec_for_json,
            client,
            model,
            metrics,
            mumei_client=mumei_client,
            enable_spec_code_mapping=bool(enable_spec_code_mapping),
        )
        dense_properties_applied = generated_code != original_code

    if mumei_client is None:
        generated_code = _regenerate_unhealthy_code(
            client,
            model,
            prompt,
            system_content,
            spec_json,
            generated_code,
            generation_config,
            past_code_examples,
            spec_for_json,
            bool(enable_dense_properties),
            metrics,
        )
        metrics.record_success("generation")
        if thought_process is not None:
            try:
                thought_process.final_success = True
                thought_process.total_attempts = 0
            except Exception:
                pass
        return generated_code, True

    # Stage 2+3: Check, verify, and targeted fix loop
    current_code = generated_code
    last_violation_type = "generation"
    health_retry_attempted = False
    for attempt in range(config_max_retries):
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".mm", delete=False, encoding="utf-8"
            ) as tmp:
                tmp_path = tmp.name
                tmp.write(current_code)

            # Parse check
            check_result = mumei_client.check(tmp_path)
            if not check_result["success"]:
                _logger.info(
                    "Multi-atom parse check failed on attempt %d: %s",
                    attempt + 1,
                    check_result["stderr"],
                )
                last_violation_type = "parse_error"
                metrics.record_attempt("parse_error")
                error_log = check_result["stdout"] + check_result["stderr"]
                current_code = _attempt_multi_atom_fix(
                    client, model, spec_json, current_code, error_log, {},
                    atom_names, metrics, spec=spec_for_json,
                    enable_spec_code_mapping=bool(enable_spec_code_mapping),
                    prompt_report_truncate_chars=prompt_report_truncate_chars,
                )
                continue

            if not health_retry_attempted and not _health_check_generated_code(
                spec_json, current_code, model, generation_config, past_code_examples,
            ):
                health_retry_attempted = True
                retry_code = _retry_for_health(
                    client,
                    model,
                    prompt,
                    system_content,
                    spec_for_json,
                    bool(enable_dense_properties),
                    metrics,
                )
                if retry_code:
                    current_code = retry_code
                continue

            # Full verification
            verify_result = _verify_with_metrics(
                mumei_client,
                tmp_path,
                spec_for_json,
                current_code,
                metrics,
                dense_properties=dense_properties_applied,
                enabled=bool(enable_spec_code_mapping),
            )
            if thought_process is not None:
                try:
                    thought_process.add_step(
                        action=(
                            "initial_verify" if attempt == 0 else "re_verify"
                        ),
                        z3_result=summarize_z3_result(verify_result),
                        verification_success=bool(verify_result["success"]),
                        re_verify_success=(
                            bool(verify_result["success"]) if attempt > 0 else None
                        ),
                    )
                except Exception:
                    pass
            if verify_result["success"]:
                metrics.record_success(last_violation_type)
                if thought_process is not None:
                    try:
                        thought_process.final_success = True
                        # Count verification steps rather than loop
                        # iterations so the early-exit and post-loop
                        # paths agree on ``total_attempts`` semantics
                        # (parse-error iterations don't add steps).
                        thought_process.total_attempts = len(
                            [
                                s
                                for s in thought_process.steps
                                if s.action in ("initial_verify", "re_verify")
                            ]
                        )
                    except Exception:
                        pass
                return current_code, True

            _logger.info(
                "Multi-atom verification failed on attempt %d", attempt + 1,
            )
            error_log = verify_result["stdout"] + verify_result["stderr"]
            report = verify_result["report"] or {}
            violation_type = report.get(
                "violation_type", report.get("failure_type", "unknown"),
            )
            last_violation_type = violation_type
            metrics.record_attempt(violation_type)

            # Identify which atoms failed and build targeted fix prompt
            failing = _identify_failing_atoms(report, atom_names)
            before_fix = current_code
            current_code = _attempt_multi_atom_fix(
                client, model, spec_json, current_code, error_log, report,
                failing, metrics, spec=spec_for_json,
                enable_spec_code_mapping=bool(enable_spec_code_mapping),
                prompt_report_truncate_chars=prompt_report_truncate_chars,
            )
            if thought_process is not None:
                try:
                    thought_process.add_step(
                        action="llm_fix",
                        verification_success=False,
                        fix_strategy="llm",
                        fix_description=describe_fix(report),
                        code_diff_summary=summarize_code_diff(
                            before_fix, current_code,
                        ),
                    )
                except Exception:
                    pass

        finally:
            try:
                if tmp_path:
                    Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass

    # Final check after all retries
    verified = False
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".mm", delete=False, encoding="utf-8"
        ) as tmp:
            tmp_path = tmp.name
            tmp.write(current_code)
        verify_result = _verify_with_metrics(
            mumei_client,
            tmp_path,
            spec_for_json,
            current_code,
            metrics,
            dense_properties=dense_properties_applied,
            enabled=bool(enable_spec_code_mapping),
        )
        if thought_process is not None:
            try:
                thought_process.add_step(
                    action="re_verify",
                    z3_result=summarize_z3_result(verify_result),
                    verification_success=bool(verify_result["success"]),
                    re_verify_success=bool(verify_result["success"]),
                )
            except Exception:
                pass
        if verify_result["success"]:
            metrics.record_success(last_violation_type)
            verified = True
    finally:
        try:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass

    if thought_process is not None:
        try:
            thought_process.final_success = verified
            thought_process.total_attempts = len(
                [
                    s
                    for s in thought_process.steps
                    if s.action in ("initial_verify", "re_verify")
                ]
            )
        except Exception:
            pass

    return current_code, verified


def _attempt_multi_atom_fix(
    client: OpenAI,
    model: str,
    spec_json: str,
    current_code: str,
    error_log: str,
    report: dict,
    failing_atoms: list[str],
    metrics: Metrics,
    *,
    spec: dict | None = None,
    enable_spec_code_mapping: bool = True,
    prompt_report_truncate_chars: int | None = None,
) -> str:
    """Attempt to fix specific failing atoms in a multi-atom module."""
    failing_str = ", ".join(failing_atoms)
    fix_prompt = (
        f"# Original multi-atom specification:\n{spec_json}\n\n"
        f"# Current generated code (needs fixing):\n```mumei\n{current_code}\n```\n\n"
        f"# Verification error:\n{error_log}\n\n"
    )
    if report:
        retry_context = format_retry_report_context(report, prompt_report_truncate_chars)
        if retry_context:
            fix_prompt += f"{retry_context}\n\n"
    fix_prompt += (
        f"# Failing atom(s): {failing_str}\n"
        f"Fix ONLY the failing atom(s) listed above. "
        f"Keep all other atoms unchanged. "
        f"Return the COMPLETE .mm file with all atoms."
    )

    fix_content = complete_text(
        client,
        [
            {
                "role": "system",
                "content": (
                    "You are a helpful programming assistant specializing "
                    "in the Mumei language with its effect system and Z3 formal verification. "
                    "Fix only the failing atoms in this multi-atom module."
                ),
            },
            {"role": "user", "content": fix_prompt},
        ],
        model,
    )

    fixed_code = _extract_code(fix_content)
    if not fixed_code:
        return current_code
    if enable_spec_code_mapping and spec:
        mapper = SpecCodeMapper()
        mapping_result = mapper.build_mapping(spec, fixed_code, report)
        report["spec_code_mapping"] = mapper.to_json(mapping_result.mappings)
    return fixed_code


def generate_code(
    client: OpenAI,
    model: str,
    spec: dict,
    config_max_retries: int = 5,
    mumei_client: MumeiClient | None = None,
    metrics: Metrics | None = None,
    thought_process: ThoughtProcess | None = None,
    enable_dense_properties: bool | None = None,
    enable_spec_code_mapping: bool | None = None,
    prompt_report_truncate_chars: int | None = None,
) -> tuple[str, bool]:
    """Generate Mumei code from a specification, verify, and fix if needed.

    Pipeline:
        1. Use LLM to generate .mm code from spec
        2. Run ``mumei check`` (parse check) on generated code
        3. Run ``mumei verify --json`` on generated code
        4. If verification fails, use existing fix_strategy to attempt repair
        5. Re-verify up to config_max_retries times

    Supports both single-atom specs and multi-atom specs (with ``atoms``
    array).  Multi-atom specs are delegated to :func:`generate_multi_atom`.

    Args:
        client: OpenAI-compatible client.
        model: Model name.
        spec: Specification dict with name, params, effects, etc.
        config_max_retries: Maximum number of fix attempts.
        mumei_client: MumeiClient for running check/verify.
        metrics: Optional Metrics instance for tracking.
        thought_process: Optional ThoughtProcess for explainability.
        enable_dense_properties: When true, generate dense contracts after
            initial code generation.
        enable_spec_code_mapping: When true, attach spec-to-code mapping
            metadata to verification reports.

    Returns:
        A tuple of (code, verified) where *code* is the generated (and
        potentially fixed) .mm source and *verified* indicates whether
        the code passed ``mumei verify``.
    """
    # Dispatch to multi-atom generation if spec contains atoms array
    if spec.get("atoms"):
        return generate_multi_atom(
            client, model, spec,
            config_max_retries=config_max_retries,
            mumei_client=mumei_client,
            metrics=metrics,
            thought_process=thought_process,
            enable_dense_properties=enable_dense_properties,
            enable_spec_code_mapping=enable_spec_code_mapping,
            prompt_report_truncate_chars=prompt_report_truncate_chars,
        )

    if metrics is None:
        metrics = Metrics()
    generation_config = _load_generation_config(spec)
    past_code_examples: list[str] = []

    if enable_dense_properties is None:
        enable_dense_properties = (
            generation_config.enable_dense_properties
            if generation_config is not None
            else False
        )

    if enable_spec_code_mapping is None:
        try:
            from agent.config import AgentConfig
            enable_spec_code_mapping = AgentConfig().enable_spec_code_mapping
        except Exception:
            enable_spec_code_mapping = True
    if prompt_report_truncate_chars is None:
        prompt_report_truncate_chars = _default_prompt_report_truncate_chars()

    # Extract cross_file_context without mutating the caller's spec dict —
    # ``run_refinement_loop`` (and any other caller) may reuse the same
    # spec for subsequent generate/refine iterations, and losing the
    # context after the first attempt would silently degrade retries.
    cross_file_context = spec.get("cross_file_context")

    # Phase 2-B — inject std/core.mm axioms for std/ module generation.
    core_axiom_context = _build_core_axiom_context(spec)

    spec_for_prompt = {k: v for k, v in spec.items() if k != "_agent_config"}

    prompt_module = _select_prompt_module(spec_for_prompt)
    # Exclude cross_file_context from the JSON payload so it renders as
    # readable markdown later in the prompt rather than JSON-escaped text.
    spec_for_json = {
        k: v
        for k, v in spec_for_prompt.items()
        if k != "cross_file_context"
    }
    spec_json = json.dumps(spec_for_json, indent=2, ensure_ascii=False)

    # Infer effects and contracts if context_file is provided
    inferred_context: dict | None = None
    context_file = spec_for_prompt.get("context_file")
    if context_file and mumei_client is not None:
        effects_result = mumei_client.infer_effects(context_file)
        contracts_result = mumei_client.infer_contracts(context_file)
        inferred_context = {
            "effects": effects_result.get("analysis", {}),
            "contracts": contracts_result.get("analysis", {}),
        }

    # Build skeleton
    skeleton = _build_skeleton(spec_for_prompt)

    # Stage 1: Initial generation
    metrics.record_attempt("generation")
    prompt = prompt_module.build_prompt(spec_json, "", {}, inferred_context=inferred_context)
    if core_axiom_context:
        prompt += f"\n\n{core_axiom_context}"
    if cross_file_context:
        prompt += f"\n\n{cross_file_context}"
    prompt += f"\n\n# Skeleton (fill in ___ placeholders):\n```mumei\n{skeleton}```"

    system_content = (
        "You are a helpful programming assistant specializing "
        "in the Mumei language with its effect system and Z3 formal verification."
    )
    content = complete_text(
        client,
        [
            {"role": "system", "content": system_content},
            {"role": "user", "content": prompt},
        ],
        model,
    )

    generated_code = _extract_code(content)
    if not generated_code:
        _logger.warning("LLM returned empty generation result")
        return "", False

    dense_properties_applied = False
    if enable_dense_properties:
        original_code = generated_code
        generated_code = _try_apply_dense_properties(
            generated_code,
            spec_for_json,
            client,
            model,
            metrics,
            mumei_client=mumei_client,
            enable_spec_code_mapping=bool(enable_spec_code_mapping),
        )
        dense_properties_applied = generated_code != original_code

    if mumei_client is None:
        generated_code = _regenerate_unhealthy_code(
            client,
            model,
            prompt,
            system_content,
            spec_json,
            generated_code,
            generation_config,
            past_code_examples,
            spec_for_json,
            bool(enable_dense_properties),
            metrics,
        )
        metrics.record_success("generation")
        if thought_process is not None:
            try:
                thought_process.final_success = True
                thought_process.total_attempts = 0
            except Exception:
                pass
        return generated_code, True

    # Stage 2+3: Check, verify, and fix loop
    current_code = generated_code
    last_violation_type = "generation"
    prev_report: dict | None = None
    health_retry_attempted = False
    for attempt in range(config_max_retries):
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".mm", delete=False, encoding="utf-8"
            ) as tmp:
                tmp_path = tmp.name
                tmp.write(current_code)

            # Parse check
            check_result = mumei_client.check(tmp_path)
            if not check_result["success"]:
                _logger.info(
                    "Parse check failed on attempt %d: %s",
                    attempt + 1,
                    check_result["stderr"],
                )
                last_violation_type = "parse_error"
                metrics.record_attempt("parse_error")
                error_log = check_result["stdout"] + check_result["stderr"]
                current_code = _attempt_fix(
                    client, model, spec_json, current_code, error_log, {},
                    prompt_module, metrics, inferred_context=inferred_context,
                    prev_report=prev_report, spec=spec_for_json,
                    enable_spec_code_mapping=bool(enable_spec_code_mapping),
                    prompt_report_truncate_chars=prompt_report_truncate_chars,
                )
                continue

            if not health_retry_attempted and not _health_check_generated_code(
                spec_json, current_code, model, generation_config, past_code_examples,
            ):
                health_retry_attempted = True
                retry_code = _retry_for_health(
                    client,
                    model,
                    prompt,
                    system_content,
                    spec_for_json,
                    bool(enable_dense_properties),
                    metrics,
                )
                if retry_code:
                    current_code = retry_code
                continue

            # Full verification
            verify_result = _verify_with_metrics(
                mumei_client,
                tmp_path,
                spec_for_json,
                current_code,
                metrics,
                dense_properties=dense_properties_applied,
                enabled=bool(enable_spec_code_mapping),
            )
            if thought_process is not None:
                try:
                    thought_process.add_step(
                        action=(
                            "initial_verify" if attempt == 0 else "re_verify"
                        ),
                        z3_result=summarize_z3_result(verify_result),
                        verification_success=bool(verify_result["success"]),
                        re_verify_success=(
                            bool(verify_result["success"]) if attempt > 0 else None
                        ),
                    )
                except Exception:
                    pass
            if verify_result["success"]:
                metrics.record_success(last_violation_type)
                if thought_process is not None:
                    try:
                        thought_process.final_success = True
                        # Count verification steps rather than loop
                        # iterations so the early-exit and post-loop
                        # paths agree on ``total_attempts`` semantics
                        # (parse-error iterations don't add steps).
                        thought_process.total_attempts = len(
                            [
                                s
                                for s in thought_process.steps
                                if s.action in ("initial_verify", "re_verify")
                            ]
                        )
                    except Exception:
                        pass
                return current_code, True

            _logger.info(
                "Verification failed on attempt %d", attempt + 1,
            )
            error_log = verify_result["stdout"] + verify_result["stderr"]
            report = verify_result["report"] or {}
            violation_type = report.get("violation_type", report.get("failure_type", "unknown"))
            last_violation_type = violation_type
            metrics.record_attempt(violation_type)

            before_fix = current_code
            current_code = _attempt_fix(
                client, model, spec_json, current_code, error_log, report,
                prompt_module, metrics, inferred_context=inferred_context,
                prev_report=prev_report, spec=spec_for_json,
                enable_spec_code_mapping=bool(enable_spec_code_mapping),
                prompt_report_truncate_chars=prompt_report_truncate_chars,
            )
            if thought_process is not None:
                try:
                    thought_process.add_step(
                        action="llm_fix",
                        verification_success=False,
                        fix_strategy="llm",
                        fix_description=describe_fix(report),
                        code_diff_summary=summarize_code_diff(
                            before_fix, current_code
                        ),
                    )
                except Exception:
                    pass
            prev_report = report

        finally:
            try:
                if tmp_path:
                    Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass

    # Final check after all retries
    verified = False
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".mm", delete=False, encoding="utf-8"
        ) as tmp:
            tmp_path = tmp.name
            tmp.write(current_code)
        verify_result = _verify_with_metrics(
            mumei_client,
            tmp_path,
            spec_for_json,
            current_code,
            metrics,
            dense_properties=dense_properties_applied,
            enabled=bool(enable_spec_code_mapping),
        )
        if thought_process is not None:
            try:
                thought_process.add_step(
                    action="re_verify",
                    z3_result=summarize_z3_result(verify_result),
                    verification_success=bool(verify_result["success"]),
                    re_verify_success=bool(verify_result["success"]),
                )
            except Exception:
                pass
        if verify_result["success"]:
            metrics.record_success(last_violation_type)
            verified = True
    finally:
        try:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass

    if thought_process is not None:
        try:
            thought_process.final_success = verified
            thought_process.total_attempts = len(
                [
                    s
                    for s in thought_process.steps
                    if s.action in ("initial_verify", "re_verify")
                ]
            )
        except Exception:
            pass

    return current_code, verified


def generate_code_with_mapping(
    client: OpenAI,
    model: str,
    spec: dict,
    config_max_retries: int = 5,
    mumei_client: MumeiClient | None = None,
    metrics: Metrics | None = None,
    thought_process: ThoughtProcess | None = None,
    enable_dense_properties: bool | None = None,
    enable_spec_code_mapping: bool | None = None,
) -> dict:
    """Generate code with spec-to-code mapping."""
    code, verified = generate_code(
        client,
        model,
        spec,
        config_max_retries=config_max_retries,
        mumei_client=mumei_client,
        metrics=metrics,
        thought_process=thought_process,
        enable_dense_properties=enable_dense_properties,
        enable_spec_code_mapping=enable_spec_code_mapping,
    )
    return {
        "code": code,
        "verified": verified,
        "spec_code_mapping": _spec_code_mapping_payload(
            spec,
            code,
            enabled=enable_spec_code_mapping is not False,
        ),
    }


def _try_apply_dense_properties(
    current_code: str,
    spec: dict,
    client: OpenAI,
    model: str,
    metrics: Metrics | None = None,
    *,
    mumei_client: MumeiClient | None = None,
    enable_spec_code_mapping: bool = True,
) -> str:
    """Best-effort dense property generation with safe fallback."""
    if metrics is not None:
        metrics.record_dense_property_attempt()
    try:
        from agent.dense_property_generator import DensePropertyGenerator

        dense_props = DensePropertyGenerator().generate_dense_properties(
            spec,
            current_code,
            client,
            model,
        )
        if metrics is not None:
            compression = dense_props.get("compression")
            if isinstance(compression, dict):
                ratio = compression.get("predicate_ratio")
                if isinstance(ratio, int | float):
                    metrics.record_dense_property_compression(float(ratio))
        updated_code = _apply_dense_properties(current_code, dense_props)
        if updated_code == current_code:
            return current_code
        if mumei_client is not None:
            baseline_result, baseline_seconds = _time_verify_candidate(
                mumei_client,
                current_code,
                spec,
                enabled=enable_spec_code_mapping,
            )
            dense_result, dense_seconds = _time_verify_candidate(
                mumei_client,
                updated_code,
                spec,
                enabled=enable_spec_code_mapping,
            )
            if metrics is not None:
                metrics.record_dense_property_verification_time(
                    baseline_seconds,
                    dense_seconds,
                )
                metrics.record_verification_time(dense_seconds, dense_properties=True)
            if not dense_result.get("success"):
                return current_code
            if (
                baseline_result.get("success")
                and dense_seconds > baseline_seconds * 0.8
            ):
                return current_code
        if metrics is not None:
            metrics.record_dense_property_success()
        return updated_code
    except Exception:
        _logger.warning(
            "Dense property generation failed; using original properties",
            exc_info=True,
        )
        return current_code


def _apply_dense_properties(current_code: str, dense_props: dict) -> str:
    """Replace existing first requires/ensures clauses with dense variants."""
    requires = dense_props.get("requires") or []
    ensures = dense_props.get("ensures") or []
    updated = current_code
    if requires:
        updated = re.sub(
            r"(requires\s*:\s*)([^;]+)(;)",
            lambda match: f"{match.group(1)}{str(requires[0]).strip()}{match.group(3)}",
            updated,
            count=1,
        )
    if ensures:
        updated = re.sub(
            r"(ensures\s*:\s*)([^;]+)(;)",
            lambda match: f"{match.group(1)}{str(ensures[0]).strip()}{match.group(3)}",
            updated,
            count=1,
        )
    return updated


def _build_retry_prompt(
    spec_json: str,
    current_code: str,
    error_log: str,
    report: dict,
    prompt_module,
    inferred_context: dict | None = None,
    prev_report: dict | None = None,
    prompt_report_truncate_chars: int | None = None,
) -> str:
    """Build an optimal retry prompt from a verification failure.

    The base prompt is built by the prompt module (``generate_atom`` or
    ``generate_stdlib``), which already includes actionable fix hints,
    structured unsat core when ``report`` is non-empty.
    This function adds only the cross-attempt error diff on top.
    """
    combined_source = (
        f"# Original specification:\n{spec_json}\n\n"
        f"# Current generated code (needs fixing):\n{current_code}"
    )

    # Start with the base prompt from the appropriate module
    base_prompt = prompt_module.build_prompt(
        combined_source,
        error_log,
        report,
        inferred_context=inferred_context,
        prompt_report_truncate_chars=prompt_report_truncate_chars,
    )

    # Enrich with error diff (cross-attempt context only).
    # NOTE: actionable fix hints and structured unsat core
    # are already appended by each prompt module's build_prompt(), so we only
    # add the error diff here to avoid duplicate sections.
    extra_sections: list[str] = []

    if prev_report:
        diff = format_error_diff(prev_report, report)
        if diff:
            extra_sections.append(f"# Error diff from previous attempt:\n{diff}")

        # Track suggestion evolution: when the suggestion has changed between
        # attempts and the new one is contextual (dynamically generated with
        # concrete counterexample data), highlight it so the LLM pays attention.
        prev_sug = prev_report.get("suggestion", "")
        curr_sug = report.get("suggestion", "")
        if curr_sug and curr_sug != prev_sug and is_contextual_suggestion(curr_sug):
            extra_sections.append(
                "# Updated verifier suggestion (contextual, high priority):\n"
                f"{curr_sug}"
            )

    if extra_sections:
        return base_prompt + "\n\n" + "\n\n".join(extra_sections)
    return base_prompt


def _attempt_fix(
    client: OpenAI,
    model: str,
    spec_json: str,
    current_code: str,
    error_log: str,
    report: dict,
    prompt_module,
    metrics: Metrics,
    inferred_context: dict | None = None,
    prev_report: dict | None = None,
    spec: dict | None = None,
    enable_spec_code_mapping: bool = True,
    prompt_report_truncate_chars: int | None = None,
) -> str:
    """Attempt to fix generated code using the LLM."""
    fix_prompt = _build_retry_prompt(
        spec_json, current_code, error_log, report, prompt_module,
        inferred_context=inferred_context, prev_report=prev_report,
        prompt_report_truncate_chars=prompt_report_truncate_chars,
    )

    fix_content = complete_text(
        client,
        [
            {
                "role": "system",
                "content": (
                    "You are a helpful programming assistant specializing "
                    "in the Mumei language with its effect system and Z3 formal verification. "
                    "Fix the code to pass verification."
                ),
            },
            {"role": "user", "content": fix_prompt},
        ],
        model,
    )

    fixed_code = _extract_code(fix_content)
    if not fixed_code:
        return current_code
    if enable_spec_code_mapping and spec:
        mapper = SpecCodeMapper()
        mapping_result = mapper.build_mapping(spec, fixed_code, report)
        report["spec_code_mapping"] = mapper.to_json(mapping_result.mappings)
    return fixed_code
