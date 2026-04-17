"""Generate strategy: generate -> verify -> fix pipeline."""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from pathlib import Path

from openai import OpenAI

from agent.mumei_client import MumeiClient
from agent.metrics import Metrics
from agent.prompts.report_formatter import format_error_diff, is_contextual_suggestion

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Phase 2-B — std/core.mm core-axiom injection for std/ module generation
# ---------------------------------------------------------------------------

# Sentinel used by prompt assemblers to recognise a previously-injected
# core-axiom block and avoid duplicating it.
_CORE_AXIOM_HEADER = "# Available Core Axioms (from std/core.mm)"

# Regex that captures ``type ... ;`` and ``atom NAME(...) requires: ...;
# ensures: ...;`` signatures.  Bodies (``body: { ... };``) are
# intentionally stripped so the prompt stays token-efficient.
_TYPE_DEFINITION_RE = re.compile(
    r"^\s*type\s+[A-Za-z_][A-Za-z0-9_]*\s*=.*?;\s*$",
    re.MULTILINE,
)
_ATOM_SIGNATURE_RE = re.compile(
    r"^atom\s+[A-Za-z_][A-Za-z0-9_]*\s*\([^)]*\).*?"
    r"ensures\s*:[^;]*;",
    re.DOTALL | re.MULTILINE,
)

# Cache the rendered axiom summary keyed by ``(path, mtime)`` so
# repeated generations do not re-read disk.
_CORE_AXIOM_CACHE: dict[tuple[str, float], str] = {}


def _is_std_module(spec: dict) -> bool:
    """Return ``True`` when the spec targets a ``std/`` module.

    Looks at any of ``output_path``, ``target_file``, ``module_name``,
    or ``name`` for a leading ``std/`` segment.  Module names like
    ``std/iter`` also qualify.
    """
    candidates: list[str] = []
    for key in ("output_path", "target_file", "module_name", "name"):
        value = spec.get(key)
        if isinstance(value, str) and value:
            candidates.append(value)
    for cand in candidates:
        normalised = cand.replace("\\", "/").lstrip("./")
        if normalised.startswith("std/"):
            return True
    return False


def _summarise_core_axioms(source: str) -> str:
    """Extract core axiom types + atom signatures from ``std/core.mm``.

    Strips ``body: { ... };`` blocks to keep the injected prompt small.
    """
    sections: list[str] = []

    types = [match.group(0).strip() for match in _TYPE_DEFINITION_RE.finditer(source)]
    if types:
        sections.append("\n".join(types))

    signatures: list[str] = []
    for match in _ATOM_SIGNATURE_RE.finditer(source):
        sig = re.sub(r"\s+", " ", match.group(0)).strip()
        # Close the signature cleanly (``...;`` already present from
        # the trailing ``ensures: ... ;`` capture).
        signatures.append(sig)
    if signatures:
        sections.append("\n".join(signatures))

    return "\n\n".join(sections).strip()


def _load_core_axiom_context(path: str | os.PathLike | None) -> str:
    """Return the rendered core-axiom prompt block, or ``""`` on failure.

    Silent fallback: when the path is missing or unreadable we return an
    empty string so generation continues without the extra context.
    """
    if not path:
        return ""
    try:
        file_path = Path(path).expanduser()
    except (TypeError, ValueError):
        return ""
    try:
        stat = file_path.stat()
    except OSError:
        _logger.info("core.mm not available at %s (skipping axiom injection)", path)
        return ""

    cache_key = (str(file_path), stat.st_mtime)
    cached = _CORE_AXIOM_CACHE.get(cache_key)
    if cached is not None:
        return cached

    try:
        source = file_path.read_text(encoding="utf-8")
    except OSError:
        _logger.warning("Failed to read %s for core-axiom injection", file_path)
        return ""

    summary = _summarise_core_axioms(source)
    if not summary:
        return ""

    rendered = (
        f"{_CORE_AXIOM_HEADER}\n"
        "# You SHOULD use these types and atoms instead of defining your own.\n"
        "# Import with: `import \"std/core\" as core;`\n"
        "```mumei\n"
        f"{summary}\n"
        "```"
    )
    _CORE_AXIOM_CACHE[cache_key] = rendered
    return rendered


def _build_core_axiom_context(spec: dict) -> str:
    """Return the core-axiom block for *spec*, or ``""`` if not applicable.

    Honors the ``inject_core_axioms`` flag and ``core_axiom_path`` on the
    provided ``AgentConfig`` instance (or falls back to env vars when
    no config is threaded through).  The block is only returned for
    ``std/``-targeted specs so non-stdlib generations stay untouched.
    """
    if not _is_std_module(spec):
        return ""

    # Late import to avoid a circular import: config imports dotenv/openai
    # at module load, which is otherwise heavy for unit tests.
    try:
        from agent.config import AgentConfig, _default_core_axiom_path
    except ImportError:  # pragma: no cover - defensive
        return ""

    config = spec.get("_agent_config")
    if isinstance(config, AgentConfig):
        if not config.inject_core_axioms:
            return ""
        path = config.core_axiom_path
    else:
        if os.getenv("INJECT_CORE_AXIOMS", "true").lower() in {"false", "0", "no", "off"}:
            return ""
        path = _default_core_axiom_path()

    return _load_core_axiom_context(path)


def _extract_code(content: str) -> str:
    """Extract code from markdown fences or return raw content."""
    code_match = re.search(r'```\w*\s*\n(.*?)```', content, re.DOTALL)
    if code_match:
        return code_match.group(1).strip()
    return content.strip()


def _has_effects(spec: dict) -> bool:
    """Check whether the spec describes an atom with effects."""
    effects = spec.get("effects", [])
    return bool(effects)


def _select_prompt_module(spec: dict):
    """Select the appropriate prompt module based on the spec."""
    if _has_effects(spec):
        from agent.prompts import generate_stdlib
        return generate_stdlib
    from agent.prompts import generate_atom
    return generate_atom


def _build_skeleton(spec: dict) -> str:
    """Build an atom skeleton from a spec for the LLM to fill in."""
    name = spec.get("name", "unnamed")
    raw_params = spec.get("inputs", spec.get("params", []))
    if not isinstance(raw_params, list):
        raw_params = []
    params = ", ".join(
        f"{p['name']}: {p.get('type', 'i64')}"
        for p in raw_params
    )
    effects = spec.get("effects", [])
    effects_str = f"    effects: [{', '.join(effects)}]\n" if effects else ""
    return (
        f"atom {name}({params})\n"
        f"{effects_str}"
        f"    requires: ___;\n"
        f"    ensures: ___;\n"
        f"    body: {{ ___ }}\n"
    )


def _detect_dependencies(atoms: list[dict]) -> dict[str, list[str]]:
    """Detect inter-atom dependencies within a multi-atom spec.

    Returns a mapping from atom name to a list of atom names it depends on
    (i.e. other atoms in the spec whose names appear in this atom's
    requires/ensures/description fields).

    Uses word-boundary matching to avoid false positives (e.g. atom
    ``div`` should not match the word ``division``).
    """
    atom_names = {a["name"] for a in atoms}
    deps: dict[str, list[str]] = {}
    for atom in atoms:
        name = atom["name"]
        # Collect text fields where references might appear
        searchable = " ".join(
            str(atom.get(k, ""))
            for k in ("requires", "ensures", "description")
        )
        deps[name] = [
            other for other in atom_names
            if other != name
            and re.search(r'\b' + re.escape(other) + r'\b', searchable)
        ]
    return deps


def _build_multi_atom_prompt(
    atoms: list[dict],
    deps: dict[str, list[str]],
) -> str:
    """Build a combined skeleton prompt for multiple atoms.

    If atom B depends on atom A, A's contract is included as context
    in B's skeleton section.
    """
    sections: list[str] = []
    # Build a lookup for quick access to atom specs by name
    by_name = {a["name"]: a for a in atoms}

    for atom in atoms:
        name = atom["name"]
        skeleton = _build_skeleton(atom)

        dep_context = ""
        for dep_name in deps.get(name, []):
            dep_atom = by_name[dep_name]
            dep_context += (
                f"// Dependency: {dep_name} — "
                f"requires: {dep_atom.get('requires', 'true')}, "
                f"ensures: {dep_atom.get('ensures', 'true')}\n"
            )

        section = ""
        if dep_context:
            section += f"# Context for {name}:\n{dep_context}\n"
        section += f"# Atom: {name}\n{skeleton}"
        sections.append(section)

    return "\n\n".join(sections)


def _identify_failing_atoms(
    report: dict,
    atom_names: list[str],
) -> list[str]:
    """Identify which atoms failed from a verification report.

    Falls back to returning all atom names if the failing atom cannot be
    determined from the report.
    """
    failing: list[str] = []
    # The report may contain a single "atom" field or a list of "atoms"
    report_atom = report.get("atom", "")
    report_atoms = report.get("atoms", [])

    if report_atom and report_atom in atom_names:
        failing.append(report_atom)
    for ra in report_atoms:
        name = ra if isinstance(ra, str) else ra.get("name", "")
        if name in atom_names:
            failing.append(name)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for f in failing:
        if f not in seen:
            seen.add(f)
            unique.append(f)

    return unique if unique else list(atom_names)


def generate_multi_atom(
    client: OpenAI,
    model: str,
    spec: dict,
    config_max_retries: int = 5,
    mumei_client: MumeiClient | None = None,
    metrics: Metrics | None = None,
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

    Returns:
        A tuple of (code, verified).
    """
    if metrics is None:
        metrics = Metrics()

    # Extract cross_file_context before JSON-serialising the spec so it
    # appears as readable markdown in the prompt rather than a JSON-escaped
    # string with literal ``\n`` sequences.
    cross_file_context = spec.pop("cross_file_context", None)

    # Phase 2-B — always inject std/core.mm axioms when targeting a
    # std/ module so generated atoms reuse Size/Index/NonZero and the
    # safe conversion atoms instead of redefining them.
    core_axiom_context = _build_core_axiom_context(spec)

    # Remove the scratch ``_agent_config`` pointer (if any) before the
    # spec is JSON-serialised into the prompt.
    spec.pop("_agent_config", None)

    atoms = spec["atoms"]
    module_name = spec.get("module_name", "module")
    atom_names = [a["name"] for a in atoms]
    deps = _detect_dependencies(atoms)

    # Build combined skeleton prompt
    combined_skeleton = _build_multi_atom_prompt(atoms, deps)
    spec_json = json.dumps(spec, indent=2, ensure_ascii=False)

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

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a helpful programming assistant specializing "
                    "in the Mumei language with its effect system and Z3 formal verification. "
                    "Generate a complete module with multiple atoms."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    )

    generated_code = _extract_code(response.choices[0].message.content or "")
    if not generated_code:
        _logger.warning("LLM returned empty multi-atom generation result")
        return "", False

    if mumei_client is None:
        metrics.record_success("generation")
        return generated_code, True

    # Stage 2+3: Check, verify, and targeted fix loop
    current_code = generated_code
    last_violation_type = "generation"
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
                    atom_names, metrics,
                )
                continue

            # Full verification
            verify_result = mumei_client.verify(tmp_path)
            if verify_result["success"]:
                metrics.record_success(last_violation_type)
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
            current_code = _attempt_multi_atom_fix(
                client, model, spec_json, current_code, error_log, report,
                failing, metrics,
            )

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
        verify_result = mumei_client.verify(tmp_path)
        if verify_result["success"]:
            metrics.record_success(last_violation_type)
            verified = True
    finally:
        try:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)
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
) -> str:
    """Attempt to fix specific failing atoms in a multi-atom module."""
    failing_str = ", ".join(failing_atoms)
    fix_prompt = (
        f"# Original multi-atom specification:\n{spec_json}\n\n"
        f"# Current generated code (needs fixing):\n```mumei\n{current_code}\n```\n\n"
        f"# Verification error:\n{error_log}\n\n"
    )
    if report:
        fix_prompt += f"# Structured report:\n{json.dumps(report, indent=2)}\n\n"
    fix_prompt += (
        f"# Failing atom(s): {failing_str}\n"
        f"Fix ONLY the failing atom(s) listed above. "
        f"Keep all other atoms unchanged. "
        f"Return the COMPLETE .mm file with all atoms."
    )

    fix_response = client.chat.completions.create(
        model=model,
        messages=[
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
    )

    fixed_code = _extract_code(fix_response.choices[0].message.content or "")
    if not fixed_code:
        return current_code
    return fixed_code


def generate_code(
    client: OpenAI,
    model: str,
    spec: dict,
    config_max_retries: int = 5,
    mumei_client: MumeiClient | None = None,
    metrics: Metrics | None = None,
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
        )

    if metrics is None:
        metrics = Metrics()

    # Extract cross_file_context before JSON-serialising the spec so it
    # appears as readable markdown in the prompt rather than a JSON-escaped
    # string with literal ``\n`` sequences.
    cross_file_context = spec.pop("cross_file_context", None)

    # Phase 2-B — inject std/core.mm axioms for std/ module generation.
    core_axiom_context = _build_core_axiom_context(spec)

    # Drop the scratch config pointer (if present) before JSON-serialising.
    spec.pop("_agent_config", None)

    prompt_module = _select_prompt_module(spec)
    spec_json = json.dumps(spec, indent=2, ensure_ascii=False)

    # Infer effects and contracts if context_file is provided
    inferred_context: dict | None = None
    context_file = spec.get("context_file")
    if context_file and mumei_client is not None:
        effects_result = mumei_client.infer_effects(context_file)
        contracts_result = mumei_client.infer_contracts(context_file)
        inferred_context = {
            "effects": effects_result.get("analysis", {}),
            "contracts": contracts_result.get("analysis", {}),
        }

    # Build skeleton
    skeleton = _build_skeleton(spec)

    # Stage 1: Initial generation
    metrics.record_attempt("generation")
    prompt = prompt_module.build_prompt(spec_json, "", {}, inferred_context=inferred_context)
    if core_axiom_context:
        prompt += f"\n\n{core_axiom_context}"
    if cross_file_context:
        prompt += f"\n\n{cross_file_context}"
    prompt += f"\n\n# Skeleton (fill in ___ placeholders):\n```mumei\n{skeleton}```"

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a helpful programming assistant specializing "
                    "in the Mumei language with its effect system and Z3 formal verification."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    )

    generated_code = _extract_code(response.choices[0].message.content or "")
    if not generated_code:
        _logger.warning("LLM returned empty generation result")
        return "", False

    if mumei_client is None:
        metrics.record_success("generation")
        return generated_code, True

    # Stage 2+3: Check, verify, and fix loop
    current_code = generated_code
    last_violation_type = "generation"
    prev_report: dict | None = None
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
                    prev_report=prev_report,
                )
                continue

            # Full verification
            verify_result = mumei_client.verify(tmp_path)
            if verify_result["success"]:
                metrics.record_success(last_violation_type)
                return current_code, True

            _logger.info(
                "Verification failed on attempt %d", attempt + 1,
            )
            error_log = verify_result["stdout"] + verify_result["stderr"]
            report = verify_result["report"] or {}
            violation_type = report.get("violation_type", report.get("failure_type", "unknown"))
            last_violation_type = violation_type
            metrics.record_attempt(violation_type)

            current_code = _attempt_fix(
                client, model, spec_json, current_code, error_log, report,
                prompt_module, metrics, inferred_context=inferred_context,
                prev_report=prev_report,
            )
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
        verify_result = mumei_client.verify(tmp_path)
        if verify_result["success"]:
            metrics.record_success(last_violation_type)
            verified = True
    finally:
        try:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass

    return current_code, verified


def _build_retry_prompt(
    spec_json: str,
    current_code: str,
    error_log: str,
    report: dict,
    prompt_module,
    inferred_context: dict | None = None,
    prev_report: dict | None = None,
) -> str:
    """Build an optimal retry prompt from a verification failure.

    The base prompt is built by the prompt module (``generate_atom`` or
    ``generate_stdlib``), which already includes actionable fix hints,
    structured unsat core, and data flow trace when ``report`` is non-empty.
    This function adds only the cross-attempt error diff on top.
    """
    combined_source = (
        f"# Original specification:\n{spec_json}\n\n"
        f"# Current generated code (needs fixing):\n{current_code}"
    )

    # Start with the base prompt from the appropriate module
    base_prompt = prompt_module.build_prompt(
        combined_source, error_log, report, inferred_context=inferred_context,
    )

    # Enrich with error diff (cross-attempt context only).
    # NOTE: actionable fix hints, structured unsat core, and data flow trace
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
) -> str:
    """Attempt to fix generated code using the LLM."""
    fix_prompt = _build_retry_prompt(
        spec_json, current_code, error_log, report, prompt_module,
        inferred_context=inferred_context, prev_report=prev_report,
    )

    fix_response = client.chat.completions.create(
        model=model,
        messages=[
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
    )

    fixed_code = _extract_code(fix_response.choices[0].message.content or "")
    if not fixed_code:
        return current_code
    return fixed_code
