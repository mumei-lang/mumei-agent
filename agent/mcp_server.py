"""mumei-agent MCP server (P10).

Exposes mumei-agent's autonomous capabilities (forge / heal / health /
propose / log / status) as `Model Context Protocol`_ tools so external
AI agents (Claude Code, Devin, Codex, etc.) can drive the same forge
loop that ``python -m agent ...`` exposes on the CLI.

The server is a thin wrapper around the existing modules:

- :mod:`agent.forge` — :class:`agent.forge.MumeiForge` for ``forge_task``.
- :mod:`agent.self_healing` / :mod:`agent.strategies.fix_strategy` for
  ``heal_file``.
- :mod:`agent.std_health` for ``measure_std_health``.
- :mod:`agent.proliferate` (which re-exports :mod:`agent.gap_rules` /
  optionally delegates to mumei's MCP server) for
  ``propose_forge_tasks``.
- :class:`agent.mumei_client.MumeiClient` for any subprocess work.

Running the server::

    python -m agent mcp-server

.. _Model Context Protocol: https://modelcontextprotocol.io/
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from agent import telemetry
from agent.nlae_pipeline import NLAEPipeline
from agent.prompts.spec_guide import SPEC_GUIDE_DECIDABLE_FRAGMENT

logger = logging.getLogger(__name__)

mcp = FastMCP("Mumei-Agent")
_active_human_review_tracker = None

from agent.mcp_server_helpers import (
    _carrier_from_ctx,
    _err,
    _existing_path_arg,
    _env_bool,
    _json_object_arg,
    _llm_client_for_context,
    _llm_provider_for_context,
    _ok,
    _ok_dataclass,
    _parse_error_report,
    _parse_spec_files,
    _resolve_repo,
    _sampling_enabled,
)

def _heal_single_file(
    code_file: Path,
    *,
    error_report: str = "",
    config: Any | None = None,
    client: Any | None = None,
    mumei: Any | None = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Heal one on-disk ``.mm`` file and overwrite it with the candidate fix."""
    try:
        from agent.config import AgentConfig
        from agent.mumei_client import create_mumei_client
        from agent.strategies import fix_strategy
    except Exception as exc:  # pragma: no cover - defensive
        return {"file": str(code_file), "success": False, "attempts": 0, "error": str(exc)}

    try:
        config = config or AgentConfig()
        client = client or _llm_client_for_context(config, ctx)
        mumei = mumei or create_mumei_client(config.mumei_bin)
    except Exception as exc:
        return {
            "file": str(code_file),
            "success": False,
            "attempts": 0,
            "error": f"AgentConfig is unavailable: {exc}",
            "hint": "set LLM_API_KEY / OPENAI_API_KEY or enable USE_MCP_SAMPLING from an MCP client",
        }

    try:
        source_code = code_file.read_text(encoding="utf-8")
    except OSError as exc:
        return {"file": str(code_file), "success": False, "attempts": 0, "error": str(exc)}

    report_data, error_log = _parse_error_report(error_report)
    if not error_report:
        try:
            verify = mumei.verify(str(code_file))
        except Exception as exc:
            verify = {"success": False, "stdout": "", "stderr": str(exc), "report": {}}
        report_data = verify.get("report") or {}
        error_log = verify.get("stderr") or verify.get("stdout") or ""
        if verify.get("success"):
            return {
                "file": str(code_file),
                "success": True,
                "attempts": 0,
                "note": "source already verifies; no heal needed",
            }

    try:
        healed = fix_strategy.get_fix(
            client=client,
            model=config.model,
            source_code=source_code,
            error_log=error_log or "",
            report_data=report_data,
            strategy=getattr(config, "strategy", "single"),
            mumei_client=mumei,
            source_path=str(code_file),
        )
    except Exception as exc:
        return {"file": str(code_file), "success": False, "attempts": 1, "error": str(exc)}

    if not healed:
        return {
            "file": str(code_file),
            "success": False,
            "attempts": 1,
            "error": "fix strategy returned an empty candidate",
            "manual_review_required": report_data.get("manual_review_required"),
        }

    try:
        code_file.write_text(healed, encoding="utf-8")
    except OSError as exc:
        return {"file": str(code_file), "success": False, "attempts": 1, "error": str(exc)}

    return {
        "file": str(code_file),
        "success": True,
        "attempts": 1,
        "healed_code": healed,
    }

def _heal_directory(
    code_dir: Path,
    error_report: str = "",
    ctx: Context | None = None,
) -> str:
    try:
        from agent.config import AgentConfig
        from agent.mumei_client import create_mumei_client
        from agent.strategies.fix_strategy import (
            _aggregate_heal_results,
            build_dependency_graph,
            topological_sort_files,
        )
    except Exception as exc:  # pragma: no cover - defensive
        return _err(f"failed to import agent modules: {exc}")

    mm_files = sorted(code_dir.rglob("*.mm"))
    if not mm_files:
        return _err(f"no .mm files found under {code_dir}")

    import warnings

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        graph = build_dependency_graph(mm_files)
        ordered_files = topological_sort_files(graph)

    if captured:
        warnings_payload = [str(item.message) for item in captured]
        results = [
            {
                "file": str(path),
                "success": False,
                "attempts": 0,
                "error": "cyclic dependency requires manual review",
                "manual_review_required": {
                    "reason": "cyclic_dependency",
                    "warnings": warnings_payload,
                },
            }
            for path in ordered_files
        ]
        payload = _aggregate_heal_results(results)
        payload["ordered_files"] = [str(path) for path in ordered_files]
        payload["warnings"] = warnings_payload
        payload["manual_review_required"] = {
            "reason": "cyclic_dependency",
            "warnings": warnings_payload,
        }
        return _ok(payload)

    try:
        config = AgentConfig()
        client = _llm_client_for_context(config, ctx)
        mumei = create_mumei_client(config.mumei_bin)
    except Exception as exc:
        return _err(
            f"AgentConfig is unavailable: {exc}",
            hint="set LLM_API_KEY / OPENAI_API_KEY or enable USE_MCP_SAMPLING from an MCP client",
        )

    tracer = telemetry.get_tracer(__name__)
    results = []
    for path in ordered_files:
        with tracer.start_as_current_span(
            "mcp.tool.heal_file.file",
            attributes={"mcp.tool.name": "heal_file", "mumei.heal.file": str(path)},
        ):
            results.append(
                _heal_single_file(
                    path,
                    error_report=error_report,
                    config=config,
                    client=client,
                    mumei=mumei,
                    ctx=ctx,
                )
            )
    payload = _aggregate_heal_results(results)
    payload["ordered_files"] = [str(path) for path in ordered_files]
    return _ok(payload)

_SPEC_GUIDELINES: dict[str, Any] = {
    "summary": "Prefer the Z3-stable decidable fragment before escalating to Lean.",
    "fragment_catalog": [
        {
            "name": "linear_arithmetic",
            "recommended": [
                "i64/Nat refinements with addition, subtraction, comparisons, and constant multiplication",
                "explicit finite bounds for overflow-prone arithmetic",
            ],
            "lean_escalation_candidates": [
                "variable * variable",
                "symbolic division or modulo",
                "exponentiation or recursive arithmetic invariants",
            ],
        },
        {
            "name": "array_and_sequence_access",
            "recommended": [
                "require 0 <= i and i < len(a) before a[i]",
                "single-index reads/writes and length-preserving updates",
            ],
            "lean_escalation_candidates": [
                "multi-index relational updates",
                "unbounded quantified array triggers",
            ],
        },
        {
            "name": "quantifiers",
            "recommended": [
                "forall over bounded ranges or finite collections",
                "exists with a constructible witness exposed in the spec",
            ],
            "lean_escalation_candidates": [
                "forall/exists alternation",
                "nested quantifiers or array-trigger-heavy bodies",
            ],
        },
        {
            "name": "effects_and_temporal_state",
            "recommended": [
                "finite state machines with explicit transitions",
                "explicit pre/post effect states for temporal protocols",
            ],
            "lean_escalation_candidates": [
                "recursive or unbounded temporal invariants",
                "large protocol products without decomposition",
            ],
        },
    ],
    "warning": {
        "code": "outside_decidable_fragment",
        "response": "simplify the spec, add explicit bounds/witnesses, or route the obligation to Lean",
    },
    "metric_refresh": {
        "source": "P8-C metrics",
        "fields": [
            "new_spec_attempts",
            "outside_decidable_fragment_warnings",
            "z3_unknowns",
            "first_pass_verification_success_rate",
            "by_logic_fragment",
        ],
        "cadence": "quarterly",
    },
}

@mcp.tool()
def get_spec_guide_summary() -> str:
    """Return the agent-facing decidable-fragment guideline summary."""
    return _ok({"summary": SPEC_GUIDE_DECIDABLE_FRAGMENT})

@mcp.tool()
def get_spec_guidelines() -> str:
    """Return agent-facing guidance for proof-friendly Mumei specifications."""
    return _ok({"guidelines": _SPEC_GUIDELINES})

@mcp.tool()
def forge_task(
    task_json: str,
    mumei_repo: str,
    dry_run: bool = True,
    ctx: Context | None = None,
) -> str:
    """Run a single forge task spec via :class:`agent.forge.MumeiForge`.

    Args:
        task_json: JSON string containing a forge task spec
            (see ``forge_tasks/README.md`` and ``vstd_*.json`` examples).
        mumei_repo: Filesystem path to the mumei repo checkout.
        dry_run: When true (default), do not call the LLM or commit
            anything; just return a planned outcome.

    Returns:
        JSON string with ``task_id``, ``status``, ``target_file``,
        ``error`` and ``code_length`` fields.
    """
    with telemetry.start_tool_span(
        "forge_task", carrier=_carrier_from_ctx(ctx),
        **{"mcp.tool.dry_run": dry_run},
    ) as span:
        try:
            task = json.loads(task_json)
        except json.JSONDecodeError as exc:
            return _err(f"task_json is not valid JSON: {exc}")
        if not isinstance(task, dict):
            return _err("task_json must decode to a JSON object")

        span.set_attribute("mcp.tool.task_id", task.get("task_id", "unknown"))

        repo = _resolve_repo(mumei_repo)
        if not repo.exists():
            return _err(f"mumei_repo does not exist: {repo}")

        # Lazy imports keep the module importable in environments without the
        # OpenAI client (e.g. the tools-only CI used by the unit tests).
        try:
            from agent.config import AgentConfig
            from agent.forge import MumeiForge
            from agent.mumei_client import create_mumei_client
        except Exception as exc:  # pragma: no cover - defensive
            return _err(f"failed to import agent modules: {exc}")

        config: AgentConfig | None = None
        llm_provider = None
        if not dry_run:
            try:
                config = AgentConfig()
                llm_provider = _llm_provider_for_context(config, ctx)
                if llm_provider is None:
                    config.create_client()
            except Exception as exc:
                return _err(
                    f"AgentConfig is unavailable: {exc}",
                    hint="set LLM_API_KEY, enable USE_MCP_SAMPLING from an MCP client, or run with dry_run=true",
                )

        mumei_bin = (config.mumei_bin if config else None) or os.environ.get(
            "MUMEI_BIN", "mumei"
        )
        # Honor ``USE_MCP_CLIENT`` for forge_task so MCP-backed verification
        # is available from both the CLI and the MCP entrypoint.
        mumei_client = create_mumei_client(mumei_bin)
        forge_tasks_dir = repo.parent / "mumei-agent" / "forge_tasks"
        if not forge_tasks_dir.exists():
            forge_tasks_dir = repo / "forge_tasks"

        forge = MumeiForge(
            config=config,
            mumei_client=mumei_client,
            mumei_repo_dir=repo,
            forge_tasks_dir=forge_tasks_dir,
            llm_provider=llm_provider,
        )

        if dry_run:
            return _ok(
                {
                    "task_id": task.get("task_id", "unknown"),
                    "status": "skipped",
                    "target_file": task.get("target_file"),
                    "error": "dry-run",
                    "code_length": 0,
                    "dry_run": True,
                }
            )

        try:
            result = forge.forge_one(task)
        except Exception as exc:
            return _err(
                f"forge_one raised: {exc}",
                task_id=task.get("task_id", "unknown"),
                target_file=task.get("target_file"),
            )

        span.set_attribute("mcp.tool.status", result.status)

        # Mirror ``MumeiForge.run()`` (agent/forge.py:151-152) so MCP-driven
        # tasks land in ``forge_log.json`` and ``filter_completed_tasks``
        # deduplicates them on subsequent CLI / MCP runs.  Logging failures
        # must not fail the tool call — the task itself already succeeded.
        try:
            forge.log_result(task, result)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("forge_task: log_result failed: %s", exc)

        code_length = 0
        target = result.target_file
        if target:
            target_path = (repo / target).resolve()
            try:
                target_path.relative_to(repo)
                if target_path.exists():
                    code_length = len(target_path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                code_length = 0

        return _ok(
            {
                "task_id": result.task_id,
                "status": result.status,
                "target_file": result.target_file,
                "error": result.error,
                "code_length": code_length,
                "attempts": result.attempts,
                "atoms_added": result.atoms_added,
                "commit_sha": result.commit_sha,
            }
        )

@mcp.tool()
def heal_file(
    source_code: str = "",
    error_report: str = "",
    code_file: str = "",
    ctx: Context | None = None,
) -> str:
    """Self-heal mumei source code or an on-disk file/directory.

    Args:
        source_code: The current ``.mm`` source code to repair. For backward
            compatibility, this may also be an existing file or directory path.
        error_report: Optional verification error report to seed the
            prompt.  When omitted, the agent runs ``mumei verify`` first
            and uses the resulting report.
        code_file: Optional path to a ``.mm`` file or directory. Directories
            are searched recursively and healed in dependency-first order.

    Returns:
        JSON string with ``healed_code``, ``attempts``, ``success``,
        and ``error`` fields.  Requires :class:`agent.config.AgentConfig`
        to be configured (LLM_API_KEY etc.); errors out cleanly with a
        descriptive ``hint`` field otherwise.
    """
    with telemetry.start_tool_span(
        "heal_file", carrier=_carrier_from_ctx(ctx),
    ) as span:
        target_arg = (code_file or "").strip()
        if target_arg:
            target_path = _existing_path_arg(target_arg)
            if target_path is None:
                return _err(f"code_file not found: {target_arg}")
        else:
            target_path = _existing_path_arg((source_code or "").strip())

        if target_path is not None:
            if target_path.is_dir():
                span.set_attribute("mumei.heal.kind", "directory")
                return _heal_directory(target_path, error_report=error_report, ctx=ctx)
            if target_path.is_file():
                span.set_attribute("mumei.heal.kind", "file")
                result = _heal_single_file(target_path, error_report=error_report, ctx=ctx)
                from agent.strategies.fix_strategy import _aggregate_heal_results

                payload = _aggregate_heal_results([result])
                payload["file"] = str(target_path)
                if result.get("healed_code"):
                    payload["healed_code"] = result["healed_code"]
                return _ok(payload)
            return _err(f"code_file must be a file or directory: {target_path}")

        span.set_attribute("mumei.heal.kind", "inline")

        if not source_code or not source_code.strip():
            return _err("source_code must be non-empty")

        try:
            from agent.config import AgentConfig
            from agent.mumei_client import create_mumei_client
            from agent.strategies.fix_strategy import get_fix
        except Exception as exc:  # pragma: no cover - defensive
            return _err(f"failed to import agent modules: {exc}")

        try:
            config = AgentConfig()
            client = _llm_client_for_context(config, ctx)
        except Exception as exc:
            return _err(
                f"AgentConfig is unavailable: {exc}",
                hint="set LLM_API_KEY / OPENAI_API_KEY or enable USE_MCP_SAMPLING from an MCP client",
            )

        report_data: dict[str, Any] = {}
        error_log = error_report
        if error_report:
            try:
                report_data = json.loads(error_report)
                if not isinstance(report_data, dict):
                    report_data = {"raw": report_data}
            except json.JSONDecodeError:
                report_data = {"raw": error_report}
        else:
            # Best-effort initial verification so the prompt has something
            # concrete to fix.  Failures are non-fatal — the LLM will simply
            # see an empty report.
            import tempfile

            # Honor ``USE_MCP_CLIENT`` for heal_file's initial verification so
            # the prompt seed benefits from the same richer semantic feedback
            # the CLI ``heal`` subcommand sees.
            mumei = create_mumei_client(config.mumei_bin)
            # Initialize to None before the try block so the ``finally``
            # clause never hits ``UnboundLocalError`` when NamedTemporaryFile
            # or tmp.write raises — matching the pattern in
            # ``agent/strategies/fix_strategy.py``.
            tmp_path: str | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    "w", suffix=".mm", delete=False, encoding="utf-8"
                ) as tmp:
                    tmp_path = tmp.name
                    tmp.write(source_code)
                verify = mumei.verify(tmp_path)
                report_data = verify.get("report") or {}
                error_log = verify.get("stderr") or verify.get("stdout") or ""
                if verify.get("success"):
                    return _ok(
                        {
                            "healed_code": source_code,
                            "attempts": 0,
                            "success": True,
                            "note": "source already verifies; no heal needed",
                        }
                    )
            finally:
                if tmp_path is not None:
                    try:
                        Path(tmp_path).unlink()
                    except Exception:
                        pass

        try:
            mumei = create_mumei_client(config.mumei_bin)
            healed = get_fix(
                client=client,
                model=config.model,
                source_code=source_code,
                error_log=error_log or "",
                report_data=report_data,
                strategy=getattr(config, "strategy", "single"),
                mumei_client=mumei,
            )
        except Exception as exc:
            return _err(f"fix_strategy.get_fix raised: {exc}")

        return _ok(
            {
                "healed_code": healed or source_code,
                "attempts": 1,
                "success": bool(healed),
            }
        )

@mcp.tool()
def self_correct(
    code_file: str,
    max_iterations: int = 10,
    ctx: Context | None = None,
) -> str:
    """P9-F: Self-Correction Protocol - 自己修復ループを実行する."""
    with telemetry.start_tool_span(
        "self_correct",
        carrier=_carrier_from_ctx(ctx),
        **{"mcp.tool.max_iterations": max_iterations},
    ):
        path = _existing_path_arg(code_file)
        if path is None or not path.is_file():
            return _err(f"code_file not found: {code_file}")

        try:
            from agent.config import AgentConfig
            from agent.mumei_client import create_mumei_client
            from agent.strategies.fix_strategy import (
                ConfiguredLossVectorFixClient,
                SelfCorrectionLoop,
            )
        except Exception as exc:  # pragma: no cover - defensive
            return _err(f"failed to import self-correction modules: {exc}")

        try:
            config = AgentConfig()
            mumei = create_mumei_client(config.mumei_bin)
            llm_provider = _llm_provider_for_context(config, ctx)
            if llm_provider is None:
                config.create_client()
        except Exception as exc:
            return _err(
                f"AgentConfig is unavailable: {exc}",
                hint="set LLM_API_KEY / OPENAI_API_KEY or enable USE_MCP_SAMPLING from an MCP client",
            )

        loop = SelfCorrectionLoop(max_iterations=max_iterations)
        llm = ConfiguredLossVectorFixClient(config, mumei, llm_provider=llm_provider)
        try:
            result = loop.run(path, mumei, llm)
        except Exception as exc:
            return _err(f"self-correction failed: {exc}")
        payload = result.to_dict()
        payload["file"] = str(path)
        return _ok(payload)

@mcp.tool()
def run_nlae_pipeline(
    spec: str,
    mumei_lean_repo: str = "",
    work_dir: str = "",
    no_build: bool = False,
) -> str:
    """P9-G: run the four-repository NLAE integration pipeline."""
    with telemetry.start_tool_span(
        "run_nlae_pipeline", **{"mcp.tool.no_build": no_build}
    ):
        lean_repo = Path(
            mumei_lean_repo
            or os.environ.get("MUMEI_LEAN_REPO", "../mumei-lean")
        ).expanduser().resolve()
        if not lean_repo.exists():
            return _err(
                f"mumei_lean_repo not found: {lean_repo}",
                hint="pass a mumei-lang/mumei-lean checkout or set MUMEI_LEAN_REPO",
            )
        pipeline_work_dir = (
            Path(work_dir).expanduser().resolve()
            if work_dir
            else Path(tempfile.mkdtemp(prefix="mumei-nlae-mcp-"))
        )
        try:
            result = NLAEPipeline(
                work_dir=pipeline_work_dir,
                lean_no_build=no_build,
            ).run_full_pipeline(spec, lean_repo)
        except Exception as exc:
            return _err(f"run_nlae_pipeline failed: {exc}")
        return _ok(result.to_dict())

@mcp.tool()
def measure_std_health(mumei_repo: str) -> str:
    """Measure proof-health metrics for the mumei std/ library.

    Delegates to :func:`agent.std_health.measure_health`.

    Returns:
        JSON string with ``total_files``, ``verified_files``,
        ``failed_files``, ``total_atoms``, ``verified_atoms``,
        ``trusted_atoms``, ``health_score``, ``todo_count``, and
        ``details``.
    """
    with telemetry.start_tool_span("measure_std_health"):
        repo = _resolve_repo(mumei_repo)
        std_dir = repo / "std"
        if not std_dir.exists():
            return _err(f"std directory not found under {repo}")

        try:
            from agent.config import AgentConfig
            from agent.mumei_client import create_mumei_client
            from agent.std_health import measure_health
        except Exception as exc:  # pragma: no cover - defensive
            return _err(f"failed to import agent modules: {exc}")

        try:
            config = AgentConfig()
            mumei_bin = config.mumei_bin
        except Exception:
            mumei_bin = os.environ.get("MUMEI_BIN", "mumei")

        mumei_client = create_mumei_client(mumei_bin)
        try:
            report = measure_health(mumei_client, std_dir)
        except Exception as exc:
            return _err(f"measure_health raised: {exc}")

        payload = dict(report)
        return _ok(payload)

@mcp.tool()
def cross_validate(spec_file: str, impl_file: str, language: str = "") -> str:
    """Cross-validate a Mumei spec (.mm) against its implementation code.

    Detects semantic gaps where the specification is stronger, weaker, or
    contradicts the implementation.  Also computes coverage of spec atoms
    against implementation functions.

    Args:
        spec_file: Path to the .mm specification file.
        impl_file: Path to the implementation source file.
        language: Language of the implementation (python/rust/typescript/go/solidity).
            Inferred from file extension if omitted.

    Returns:
        JSON string with ``spec_stronger_than_impl``,
        ``impl_stronger_than_spec``, ``uncovered_atoms``,
        ``coverage_ratio``, and ``details`` fields.
    """
    spec_path = Path(spec_file).expanduser().resolve()
    impl_path = Path(impl_file).expanduser().resolve()

    if not spec_path.exists():
        return _err(f"spec_file does not exist: {spec_path}")
    if not impl_path.exists():
        return _err(f"impl_file does not exist: {impl_path}")

    if not language:
        ext = impl_path.suffix.lower()
        lang_map = {
            ".py": "python",
            ".rs": "rust",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".js": "javascript",
            ".jsx": "javascript",
            ".go": "go",
        }
        language = lang_map.get(ext, "")
        if not language:
            return _err(
                f"cannot infer language from extension '{ext}'; please specify explicitly",
                supported=["python", "rust", "typescript", "go"],
            )

    try:
        from agent.strategies.cross_validation_strategy import CrossValidator
    except Exception as exc:  # pragma: no cover
        return _err(f"failed to import CrossValidator: {exc}")

    validator = CrossValidator()
    report = validator.validate_spec_vs_impl(
        spec_path=str(spec_path),
        impl_path=str(impl_path),
        language=language,
    )
    return _ok(report.to_dict())

@mcp.tool()
def propose_forge_tasks(mumei_repo: str, max_proposals: int = 3) -> str:
    """Propose new forge task specs from a gap analysis of *mumei_repo*.

    This is the MCP-accessible counterpart of
    ``python -m agent propose --auto``.  It runs
    :func:`agent.proliferate.analyze_gaps` (which honors
    ``PREFER_MCP_GAPS``) and converts the proposals into forge task
    specs via :func:`agent.proliferate.generate_specs_from_gaps`.

    Args:
        mumei_repo: Path to the mumei checkout.
        max_proposals: Maximum number of proposals to materialize as
            specs (default 3, matching the ``analyze_std_gaps`` cap).

    Returns:
        JSON string with ``proposals`` and ``specs`` lists.
    """
    with telemetry.start_tool_span("propose_forge_tasks"):
        if max_proposals <= 0:
            return _err("max_proposals must be positive")

        repo = _resolve_repo(mumei_repo)
        std_dir = repo / "std"
        if not std_dir.exists():
            return _err(f"std directory not found under {repo}")

        try:
            from agent.proliferate import analyze_gaps, generate_specs_from_gaps
        except Exception as exc:  # pragma: no cover - defensive
            return _err(f"failed to import agent.proliferate: {exc}")

        try:
            gaps = analyze_gaps(std_dir)
        except Exception as exc:
            return _err(f"analyze_gaps raised: {exc}")

        try:
            specs = generate_specs_from_gaps(gaps, max_count=max_proposals)
        except Exception as exc:
            return _err(f"generate_specs_from_gaps raised: {exc}")

        return _ok(
            {
                "proposals": gaps.get("proposals") or [],
                "specs": specs,
                "trusted_atoms": gaps.get("trusted_atoms") or [],
                "todo_comments": gaps.get("todo_comments") or [],
            }
        )

@mcp.tool()
def list_forge_log(log_path: str = "forge_log.json") -> str:
    """Return the contents of a forge log JSON file.

    The forge log records every completed task (success / failure /
    skipped) and is the source of truth for ``filter_completed_tasks``
    when the orchestrator decides what to do on the next run.

    Args:
        log_path: Path to ``forge_log.json``.  Relative paths are
            resolved against the current working directory.

    Returns:
        JSON string with ``entries`` (the parsed log) and ``count``.
    """
    with telemetry.start_tool_span("list_forge_log"):
        path = Path(log_path).expanduser()
        if not path.is_absolute():
            path = path.resolve()
        if not path.exists():
            return _ok(
                {
                    "entries": [],
                    "count": 0,
                    "path": str(path),
                    "note": "forge log does not exist yet",
                }
            )
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            return _err(f"failed to read {path}: {exc}")
        if not text.strip():
            return _ok({"entries": [], "count": 0, "path": str(path)})
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            return _err(f"forge log is not valid JSON: {exc}", path=str(path))
        if isinstance(data, list):
            entries = data
        elif isinstance(data, dict) and isinstance(data.get("entries"), list):
            entries = data["entries"]
        else:
            return _err(
                "unexpected forge log structure (expected list or {entries: [...]})",
                path=str(path),
            )
        return _ok({"entries": entries, "count": len(entries), "path": str(path)})

@mcp.tool()
def get_review_queue(mumei_repo: str) -> str:
    """Return the human review queue emitted by ``mumei verify``.

    Sets the active tracker for subsequent ``approve_review`` /
    ``escalate_to_lean`` calls.  Calling again with a different
    *mumei_repo* replaces the active tracker.
    """
    global _active_human_review_tracker
    try:
        from agent.human_review import HumanReviewTracker

        tracker = HumanReviewTracker.from_repo(mumei_repo)
        queue = tracker.load()
    except Exception as exc:
        return _err(f"failed to load human review queue: {exc}", mumei_repo=mumei_repo)

    _active_human_review_tracker = tracker
    atoms = queue.get("atoms", [])
    return _ok(
        {
            "queue": queue,
            "path": str(tracker.queue_path),
            "count": len(atoms) if isinstance(atoms, list) else 0,
        }
    )

@mcp.tool()
def approve_review(atom_name: str, reviewer: str, notes: str) -> str:
    """Record human approval for one atom in the active review queue."""
    try:
        tracker = _human_review_tracker()
        entry = tracker.approve_review(atom_name, reviewer, notes)
    except Exception as exc:
        return _err(f"failed to approve review: {exc}", atom_name=atom_name)
    return _ok({"atom": entry, "path": str(tracker.queue_path)})

@mcp.tool()
def escalate_to_lean(atom_name: str) -> str:
    """Run ``mumei verify --escalate-lean`` and mark an atom as escalated."""
    try:
        tracker = _human_review_tracker()
        entry = tracker.escalate_to_lean(atom_name)
    except Exception as exc:
        return _err(f"failed to escalate atom to Lean: {exc}", atom_name=atom_name)
    return _ok({"atom": entry, "path": str(tracker.queue_path)})


@mcp.tool()
def reject_review(atom_name: str, reviewer: str, notes: str) -> str:
    """Record human rejection for one atom in the active review queue."""
    try:
        tracker = _human_review_tracker()
        entry = tracker.reject_review(atom_name, reviewer, notes)
    except Exception as exc:
        return _err(f"failed to reject review: {exc}", atom_name=atom_name)
    return _ok({"atom": entry, "path": str(tracker.queue_path)})

def _human_review_tracker():
    global _active_human_review_tracker
    if _active_human_review_tracker is not None:
        return _active_human_review_tracker
    from agent.human_review import HumanReviewTracker

    _active_human_review_tracker = HumanReviewTracker.default()
    _active_human_review_tracker.load()
    return _active_human_review_tracker

@mcp.tool()
def get_agent_status() -> str:
    """Return information about the running mumei-agent installation.

    Useful for external agents (Claude Code, Devin, ...) that want to
    introspect what they can do before issuing tool calls.

    Returns:
        JSON string with the LLM provider/model, mumei binary path,
        available CLI subcommands, registered MCP tools, and the
        relevant feature-flag environment variables.
    """
    with telemetry.start_tool_span("get_agent_status"):
        try:
            from agent.config import AgentConfig
        except Exception as exc:  # pragma: no cover - defensive
            return _err(f"failed to import agent.config: {exc}")

        try:
            config = AgentConfig()
        except Exception as exc:  # pragma: no cover - defensive
            return _err(f"AgentConfig() failed: {exc}")

        try:
            from agent.__main__ import _SUBCOMMANDS

            subcommands = sorted(_SUBCOMMANDS)
        except Exception:  # pragma: no cover - defensive
            subcommands = [
                "heal",
                "generate",
                "publish",
                "forge",
                "propose",
                "analyze-std-gaps",
                "proliferate",
                "health",
                "extract-spec",
                "validate-spec",
                "validate-code",
                "validate-spec-to-code",
                "validate-code-to-spec",
                "verify-conformance",
                "verify-traceability",
                "self-correct",
                "mcp-server",
                "check-spec-health",
                "migrate-suggest",
                "cross-validate",
            ]

        return _ok(
            {
                "llm_provider": "mcp-sampling" if _sampling_enabled(config) else "openai-compatible",
                "model": config.model,
                "base_url": config.base_url,
                "mumei_bin": config.mumei_bin,
                "strategy": config.strategy,
                "subcommands": subcommands,
                "mcp_tools": sorted(mcp._tool_manager._tools),
                "feature_flags": {
                    "PREFER_MCP_GAPS": os.environ.get("PREFER_MCP_GAPS", ""),
                    "USE_MCP_CLIENT": os.environ.get("USE_MCP_CLIENT", ""),
                    "USE_MCP_SAMPLING": os.environ.get("USE_MCP_SAMPLING", ""),
                    "INJECT_CORE_AXIOMS": os.environ.get("INJECT_CORE_AXIOMS", ""),
                    "ENABLE_LATENT_DEBUG": os.environ.get("ENABLE_LATENT_DEBUG", ""),
                    "ENABLE_DENSE_PROPERTIES": os.environ.get(
                        "ENABLE_DENSE_PROPERTIES", ""
                    ),
                    "ENABLE_LATENT_PROTOCOL": os.environ.get("ENABLE_LATENT_PROTOCOL", ""),
                    "ENABLE_CODE_TO_SPEC": os.environ.get("ENABLE_CODE_TO_SPEC", ""),
                },
                "python": sys.version,
            }
        )

@mcp.tool()
def send_latent_message(
    message: str,
    context: str = "{}",
    verify: bool = True,
) -> str:
    """Send a message using the experimental latent protocol.

    Args:
        message: JSON object string representing the message.
        context: Optional JSON object string for surrounding context.
        verify: When true, verify a Mumei representation of the latent vector.
    """
    message_dict, message_error = _json_object_arg(message, "message")
    if message_error is not None:
        return _err(message_error)

    context_dict, context_error = _json_object_arg(context, "context")
    if context_error is not None:
        return _err(context_error)

    runtime, runtime_error = _latent_runtime()
    if runtime_error is not None:
        return _err(runtime_error, hint="set ENABLE_LATENT_PROTOCOL=true in .env")

    try:
        return _ok(
            _encode_latent_payload(
                runtime,
                message_dict,
                context_dict,
                verify=verify,
            )
        )
    except Exception as exc:
        logger.exception("send_latent_message failed")
        return _err(f"latent send failed: {exc}", error_type=type(exc).__name__)

@mcp.tool()
def send_latent_message_batch(messages: str, verify: bool = False) -> str:
    """Send multiple latent messages through one protocol instance."""
    try:
        batch = json.loads(messages)
    except json.JSONDecodeError as exc:
        return _err(f"messages is not valid JSON: {exc}")
    if not isinstance(batch, list):
        return _err("messages must decode to a JSON array")

    runtime, runtime_error = _latent_runtime()
    if runtime_error is not None:
        return _err(runtime_error, hint="set ENABLE_LATENT_PROTOCOL=true in .env")

    results: list[dict[str, Any]] = []
    previous_message: dict[str, Any] | None = None
    previous_context: dict[str, Any] | None = None
    total_transfer_bytes = 0
    total_reduction = 0.0
    sent = 0

    for index, item in enumerate(batch):
        if not isinstance(item, dict):
            results.append(
                {
                    "index": index,
                    "status": "error",
                    "error": "batch item must be a JSON object",
                }
            )
            continue

        raw_message = item.get("message", item)
        raw_context = item.get("context", {})
        message_dict, message_error = _json_object_arg(raw_message, "message")
        context_dict, context_error = _json_object_arg(raw_context, "context")
        if message_error is not None or context_error is not None:
            results.append(
                {
                    "index": index,
                    "status": "error",
                    "error": message_error or context_error,
                }
            )
            continue

        item_verify = bool(item.get("verify", verify))
        try:
            payload = _encode_latent_payload(
                runtime,
                message_dict,
                context_dict,
                verify=item_verify,
                previous_message=previous_message,
                previous_context=previous_context,
            )
        except Exception as exc:
            logger.exception("send_latent_message_batch item failed")
            results.append(
                {
                    "index": index,
                    "status": "error",
                    "error": f"latent send failed: {exc}",
                    "error_type": type(exc).__name__,
                }
            )
            continue

        payload["index"] = index
        results.append(payload)
        previous_message = message_dict
        previous_context = context_dict
        sent += 1
        decoded = payload["decoded"]
        total_transfer_bytes += int(decoded["transfer_bytes"])
        total_reduction += float(decoded["transfer_reduction_ratio"])

    failed = len(batch) - sent
    average_reduction = total_reduction / sent if sent else 0.0
    return _ok(
        {
            "batch_size": len(batch),
            "failed": failed,
            "results": results,
            "sent": sent,
            "total_transfer_bytes": total_transfer_bytes,
            "average_transfer_reduction_ratio": average_reduction,
        }
    )

@mcp.tool()
async def async_send_latent_message(
    message: str,
    context: str = "{}",
    verify: bool = True,
) -> str:
    """Asynchronously send a latent message without blocking MCP transport."""
    return await asyncio.to_thread(send_latent_message, message, context, verify)

def _latent_runtime() -> tuple[dict[str, Any], str | None]:
    try:
        from agent.config import AgentConfig
        from agent.latent_protocol import LatentProtocol
        from agent.mumei_client import create_mumei_client
    except Exception as exc:
        return {}, f"failed to import agent modules: {exc}"

    try:
        config = AgentConfig()
    except Exception as exc:
        return {}, f"AgentConfig() failed: {exc}"
    if not config.enable_latent_protocol:
        return {}, "ENABLE_LATENT_PROTOCOL is not enabled"

    protocol = LatentProtocol(
        encryption_key=os.environ.get("LATENT_PROTOCOL_KEY") or None,
        audit_log_path=os.environ.get("LATENT_PROTOCOL_AUDIT_LOG") or None,
    )
    return {
        "config": config,
        "create_mumei_client": create_mumei_client,
        "protocol": protocol,
    }, None

def _encode_latent_payload(
    runtime: dict[str, Any],
    message_dict: dict[str, Any],
    context_dict: dict[str, Any],
    *,
    verify: bool,
    previous_message: dict[str, Any] | None = None,
    previous_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    protocol = runtime["protocol"]
    config = runtime["config"]
    latent_vector = protocol.encode_message(
        message_dict,
        context_dict,
        previous_message=previous_message,
        previous_context=previous_context,
    )

    verification_result = None
    if verify:
        create_mumei_client = runtime["create_mumei_client"]
        mumei_client = create_mumei_client(config.mumei_bin)
        verification_result = protocol.verify_message(
            latent_vector,
            mumei_client,
        )

    return {
        "status": "ok",
        "latent_vector": latent_vector.tolist(),
        "decoded": protocol.decode_message(latent_vector),
        "verification_result": verification_result,
        "authentication_verified": protocol.verify_authentication_tag(latent_vector),
        "audit_events": len(protocol.audit_log),
    }

@mcp.tool()
def extract_spec(
    natural_language: str,
    domain_hint: str = "",
    generate: bool = False,
    mumei_repo: str = "",
    check_contradiction_only: bool = False,
    ctx: Context | None = None,
) -> str:
    """Extract a Mumei forge task spec from natural language requirements.

    This is the "Step 0" that converts human-readable requirements into
    structured forge task specs compatible with forge_task() and the
    existing generate pipeline.

    Args:
        natural_language: The requirement text in any language.
        domain_hint: Optional domain (e.g., "financial", "security").
        generate: When true, also generate and verify the code via the
            configured ``mumei`` binary (``AgentConfig.mumei_bin``).
        mumei_repo: Path to mumei repo (used by generate=true or
            check_contradiction_only=true to prefer a repo-local
            target/debug or target/release mumei binary).
        check_contradiction_only: When true, extract the spec and run only
            direct contradiction detection without code generation.

    Returns:
        JSON string with ``spec`` (the extracted forge task spec),
        and optionally ``code``, ``verified`` when generate=true.
    """
    if not natural_language.strip():
        return _err("natural_language must be non-empty")
    if generate and check_contradiction_only:
        return _err("generate and check_contradiction_only cannot both be true")

    try:
        from agent.config import AgentConfig
        from agent.metrics import Metrics
        from agent.mumei_client import create_mumei_client
        from agent.spec_extractor import (
            extract_and_generate as extract_and_generate_impl,
            extract_spec as extract_spec_impl,
        )
        from agent.extract_spec import check_spec_contradiction_from_spec
    except Exception as exc:  # pragma: no cover - defensive
        return _err(f"failed to import agent modules: {exc}")

    try:
        config = AgentConfig()
        client = _llm_client_for_context(config, ctx)
    except Exception as exc:
        return _err(
            f"AgentConfig is unavailable: {exc}",
            hint="set LLM_API_KEY / OPENAI_API_KEY or enable USE_MCP_SAMPLING from an MCP client",
        )

    mumei_bin = config.mumei_bin
    if (generate or check_contradiction_only) and mumei_repo:
        repo = _resolve_repo(mumei_repo)
        if not repo.exists():
            return _err(f"mumei_repo does not exist: {repo}")
        release_bin = repo / "target" / "release" / "mumei"
        debug_bin = repo / "target" / "debug" / "mumei"
        if release_bin.exists():
            mumei_bin = str(release_bin)
        elif debug_bin.exists():
            mumei_bin = str(debug_bin)

    mumei = create_mumei_client(mumei_bin)
    try:
        if generate:
            code, verified, spec = extract_and_generate_impl(
                client,
                config.model,
                natural_language,
                domain_hint=domain_hint,
                mumei_client=mumei,
                max_generation_retries=config.max_retries,
            )
            return _ok({"spec": spec, "code": code, "verified": verified})
        metrics = Metrics()
        spec = extract_spec_impl(
            client,
            config.model,
            natural_language,
            domain_hint=domain_hint,
            mumei_client=mumei,
            metrics=metrics,
        )
        if check_contradiction_only:
            contradiction = check_spec_contradiction_from_spec(spec, mumei)
            return _ok(
                {
                    "spec": spec,
                    **contradiction,
                    "extraction_attempts": metrics.extraction_attempts,
                    "extraction_successes": metrics.extraction_successes,
                }
            )
        return _ok(
            {
                "spec": spec,
                "extraction_attempts": metrics.extraction_attempts,
                "extraction_successes": metrics.extraction_successes,
            }
        )
    except Exception as exc:
        return _err(f"extract_spec failed: {exc}")

@mcp.tool()
def check_spec_contradiction(
    natural_language: str,
    domain_hint: str = "",
    ctx: Context | None = None,
) -> str:
    """Extract specs and return contradiction_found plus contradiction_type=spec_internal."""
    kwargs: dict[str, Any] = {
        "domain_hint": domain_hint,
        "check_contradiction_only": True,
    }
    if ctx is not None:
        kwargs["ctx"] = ctx
    return extract_spec(
        natural_language,
        **kwargs,
    )

@mcp.tool()
def check_cross_spec_consistency(spec_files: str) -> str:
    """Run mumei cross-spec verification and return cross_validation_gaps evidence.

    Args:
        spec_files: JSON array string or comma-separated list of .mm files.
    """
    files = _parse_spec_files(spec_files)
    if not files:
        return _err("spec_files must contain at least one .mm file")

    try:
        from agent.config import AgentConfig
        from agent.mumei_client import create_mumei_client
    except Exception as exc:  # pragma: no cover - defensive
        return _err(f"failed to import agent modules: {exc}")

    try:
        config = AgentConfig()
        mumei = create_mumei_client(config.mumei_bin)
    except Exception as exc:
        return _err(f"AgentConfig is unavailable: {exc}")

    for file in files:
        if not Path(file).expanduser().exists():
            return _err(f"spec file does not exist: {file}")

    primary, *extra = files
    with tempfile.TemporaryDirectory(prefix="mumei-cross-spec-") as tmp:
        report_dir = Path(tmp) / "report"
        extra_args = ["--cross-spec-verify"]
        if extra:
            extra_args.extend(["--cross-spec-files", ",".join(extra)])
        result = mumei.verify(primary, report_dir=str(report_dir), extra_args=extra_args)
        report_path = report_dir / "cross_spec.json"
        cross_spec_report: dict[str, Any] = {}
        if report_path.exists():
            try:
                cross_spec_report = json.loads(report_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                return _err(f"failed to parse cross_spec.json: {exc}")

    return _ok(
        {
            "spec_files": files,
            "consistent": result.get("success", False)
            and not cross_spec_report.get("summary", {}).get("inconsistent_calls", 0)
            and not cross_spec_report.get("summary", {}).get(
                "global_invariant_conflict_count", 0
            ),
            "verification": result,
            "cross_spec": cross_spec_report,
        }
    )

@mcp.tool()
def check_spec_health(source_code: str, mumei_repo: str = "") -> str:
    """Check a Mumei specification for contradictions, over-constraints, and vacuity.

    Writes *source_code* to a temporary ``.mm`` file, runs
    ``mumei verify --json --enable-vacuity-check --proof-cert`` and
    analyses the proof certificate with
    :class:`agent.strategies.spec_health_strategy.SpecHealthChecker`.

    Args:
        source_code: Mumei source code (``.mm`` content) to check.
        mumei_repo: Optional path to the mumei repo.  Used to locate a
            repo-local ``mumei`` binary when ``MUMEI_BIN`` is not set.

    Returns:
        JSON string with ``contradictions``, ``over_constrained``,
        ``vacuous``, and ``health_score`` fields.
    """
    try:
        from agent.mumei_client import create_mumei_client
        from agent.strategies.spec_health_strategy import SpecHealthChecker
    except Exception as exc:  # pragma: no cover - defensive
        return _err(f"failed to import agent modules: {exc}")

    mumei_bin = os.environ.get("MUMEI_BIN", "")
    if not mumei_bin and mumei_repo:
        repo = _resolve_repo(mumei_repo)
        for profile in ("release", "debug"):
            candidate = repo / "target" / profile / "mumei"
            if candidate.exists():
                mumei_bin = str(candidate)
                break
    mumei_bin = mumei_bin or "mumei"

    mumei_client = create_mumei_client(mumei_bin)
    checker = SpecHealthChecker()

    with tempfile.TemporaryDirectory(prefix="mumei-spec-health-") as tmp:
        mm_path = Path(tmp) / "spec_health_input.mm"
        mm_path.write_text(source_code, encoding="utf-8")
        cert_path = str(Path(tmp) / "health.proof.json")
        verify_result = mumei_client.verify(
            str(mm_path),
            report_dir=tmp,
            extra_args=[
                "--enable-vacuity-check",
                "--proof-cert",
                "--output",
                cert_path,
            ],
        )
        cert_file = Path(cert_path)
        proof_cert = None
        if cert_file.exists():
            try:
                proof_cert = json.loads(cert_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass

    report = checker.check_all(verify_result, proof_cert)
    return _ok(report.to_dict())

@mcp.tool()
def validate_nl_spec(
    spec_text: str,
    use_llm: bool = True,
    run_mumei: bool = True,
    domain_hint: str = "",
    ctx: Context | None = None,
) -> str:
    """Validate a natural-language specification for logical health."""
    try:
        from agent import cross_validation
        from agent.config import AgentConfig
    except Exception as exc:  # pragma: no cover - defensive
        return _err(f"failed to import cross-validation modules: {exc}")

    try:
        config = AgentConfig()
        llm_provider = _llm_provider_for_context(config, ctx)
    except Exception as exc:
        return _err(
            f"AgentConfig is unavailable: {exc}",
            hint="set LLM_API_KEY / OPENAI_API_KEY or enable USE_MCP_SAMPLING from an MCP client",
        )

    try:
        result = cross_validation.validate_nl_spec(
            spec_text,
            config=config,
            use_llm=use_llm,
            run_mumei=run_mumei,
            domain_hint=domain_hint,
            llm_provider=llm_provider,
        )
    except Exception as exc:
        return _err(f"validate_nl_spec failed: {exc}")
    payload = asdict(result)
    issues = [
        *result.contradictions,
        *result.ambiguities,
        *result.overconstraints,
    ]
    payload["fix_suggestions"] = cross_validation._fix_suggestions(issues)
    return _ok(payload)

@mcp.tool()
def validate_nl_spec_multi(
    spec_texts_json: str,
    domain_hint: str = "",
    use_llm: bool = True,
    ctx: Context | None = None,
) -> str:
    """Validate multiple NL spec documents for cross-document consistency.

    Args:
        spec_texts_json: JSON array of spec text strings.
        domain_hint: Optional domain hint.
        use_llm: Whether to use LLM extraction before cross-document checks.
    """
    try:
        from agent import cross_validation
        from agent.config import AgentConfig
    except Exception as exc:  # pragma: no cover - defensive
        return _err(f"failed to import cross-validation modules: {exc}")

    try:
        raw = json.loads(spec_texts_json)
    except json.JSONDecodeError as exc:
        return _err(f"failed to parse spec_texts_json: {exc}")
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        return _err("spec_texts_json must be a JSON array of strings")

    try:
        config = AgentConfig()
        llm_provider = _llm_provider_for_context(config, ctx)
    except Exception as exc:
        return _err(
            f"AgentConfig is unavailable: {exc}",
            hint="set LLM_API_KEY / OPENAI_API_KEY or enable USE_MCP_SAMPLING from an MCP client",
        )

    try:
        result = cross_validation.validate_nl_spec_multi(
            raw,
            config=config,
            use_llm=use_llm,
            domain_hint=domain_hint,
            llm_provider=llm_provider,
        )
    except Exception as exc:
        return _err(f"validate_nl_spec_multi failed: {exc}")
    return _ok(result)

def _validate_existing_code_payload(
    code: str,
    language: str,
    *,
    use_llm: bool = True,
    run_mumei: bool = True,
    tool_name: str,
    ctx: Context | None = None,
) -> str:
    try:
        from agent import cross_validation
        from agent.config import AgentConfig
    except Exception as exc:  # pragma: no cover - defensive
        return _err(f"failed to import cross-validation modules: {exc}")

    try:
        config = AgentConfig()
        llm_provider = _llm_provider_for_context(config, ctx)
    except Exception as exc:
        return _err(
            f"AgentConfig is unavailable: {exc}",
            hint="set LLM_API_KEY / OPENAI_API_KEY or enable USE_MCP_SAMPLING from an MCP client",
        )

    try:
        result = cross_validation.validate_foreign_code(
            code,
            language,
            config=config,
            use_llm=use_llm,
            run_mumei=run_mumei,
            llm_provider=llm_provider,
        )
    except Exception as exc:
        return _err(f"{tool_name} failed: {exc}")
    return _ok_dataclass(result)

@mcp.tool()
def validate_code(
    code: str,
    language: str,
    use_llm: bool = True,
    run_mumei: bool = True,
    ctx: Context | None = None,
) -> str:
    """Infer and verify contracts from existing code (Python, Rust, TypeScript, Go, Solidity)."""
    return _validate_existing_code_payload(
        code,
        language,
        use_llm=use_llm,
        run_mumei=run_mumei,
        tool_name="validate_code",
        ctx=ctx,
    )

@mcp.tool()
def validate_foreign_code(
    code: str,
    language: str,
    use_llm: bool = True,
    run_mumei: bool = True,
    ctx: Context | None = None,
) -> str:
    """Infer and verify contracts from existing code (Python, Rust, TypeScript, Go, Solidity)."""
    return _validate_existing_code_payload(
        code,
        language,
        use_llm=use_llm,
        run_mumei=run_mumei,
        tool_name="validate_foreign_code",
        ctx=ctx,
    )

@mcp.tool()
def validate_spec_to_code(
    spec: str,
    code_path: str,
    language: str | None = None,
    use_llm: bool = True,
    run_mumei: bool = True,
    ctx: Context | None = None,
) -> str:
    """Validate that a natural-language specification aligns with source code."""
    try:
        from agent import cross_validation
        from agent.config import AgentConfig
    except Exception as exc:  # pragma: no cover - defensive
        return _err(f"failed to import cross-validation modules: {exc}")

    try:
        config = AgentConfig()
        llm_provider = _llm_provider_for_context(config, ctx)
    except Exception as exc:
        return _err(
            f"AgentConfig is unavailable: {exc}",
            hint="set LLM_API_KEY / OPENAI_API_KEY or enable USE_MCP_SAMPLING from an MCP client",
        )

    try:
        result = cross_validation.validate_spec_to_code(
            spec,
            code_path,
            config=config,
            language=language,
            use_llm=use_llm,
            run_mumei=run_mumei,
            llm_provider=llm_provider,
        )
    except Exception as exc:
        return _err(f"validate_spec_to_code failed: {exc}")
    return _ok_dataclass(result)

@mcp.tool()
def validate_code_to_spec(
    code_path: str,
    spec_path: str,
    language: str | None = None,
    use_llm: bool = True,
    run_mumei: bool = True,
    ctx: Context | None = None,
) -> str:
    """Detect drift between source code and a natural-language specification."""
    try:
        from agent import cross_validation
        from agent.config import AgentConfig
    except Exception as exc:  # pragma: no cover - defensive
        return _err(f"failed to import cross-validation modules: {exc}")

    try:
        config = AgentConfig()
        llm_provider = _llm_provider_for_context(config, ctx)
    except Exception as exc:
        return _err(
            f"AgentConfig is unavailable: {exc}",
            hint="set LLM_API_KEY / OPENAI_API_KEY or enable USE_MCP_SAMPLING from an MCP client",
        )

    try:
        result = cross_validation.validate_code_to_spec(
            code_path,
            spec_path,
            config=config,
            language=language,
            use_llm=use_llm,
            run_mumei=run_mumei,
            llm_provider=llm_provider,
        )
    except Exception as exc:
        return _err(f"validate_code_to_spec failed: {exc}")
    return _ok_dataclass(result)

@mcp.tool()
def verify_conformance(
    spec: str,
    code_path: str,
    language: str | None = None,
    use_llm: bool = True,
    run_mumei: bool = True,
    ctx: Context | None = None,
) -> dict:
    """Return structured spec-to-code conformance JSON with next_steps handoff."""
    try:
        from agent.config import AgentConfig
        from agent.conformance_verifier import verify_conformance as run_verification
    except Exception as exc:  # pragma: no cover - defensive
        return {"status": "error", "error": f"failed to import conformance modules: {exc}"}

    try:
        config = AgentConfig()
        llm_provider = _llm_provider_for_context(config, ctx)
    except Exception as exc:
        return {
            "status": "error",
            "error": f"AgentConfig is unavailable: {exc}",
            "hint": "set LLM_API_KEY / OPENAI_API_KEY or enable USE_MCP_SAMPLING from an MCP client",
        }

    try:
        result = run_verification(
            spec,
            code_path,
            config=config,
            language=language,
            use_llm=use_llm,
            run_mumei=run_mumei,
            llm_provider=llm_provider,
        )
    except Exception as exc:
        return {"status": "error", "error": f"verify_conformance failed: {exc}"}
    payload = asdict(result)
    payload["status"] = "ok" if result.success else "needs_review"
    return payload

@mcp.tool()
def verify_code_spec_traceability(
    code_file: str,
    spec_text: str,
    language: str | None = None,
    use_llm: bool = True,
    run_mumei: bool = True,
    ctx: Context | None = None,
) -> dict:
    """Return bidirectional spec/code traceability JSON with next_steps handoff."""
    try:
        from agent.config import AgentConfig
        from agent.traceability_verifier import verify_traceability as run_verification
    except Exception as exc:  # pragma: no cover - defensive
        return {"status": "error", "error": f"failed to import traceability modules: {exc}"}

    try:
        config = AgentConfig()
        llm_provider = _llm_provider_for_context(config, ctx)
    except Exception as exc:
        return {
            "status": "error",
            "error": f"AgentConfig is unavailable: {exc}",
            "hint": "set LLM_API_KEY / OPENAI_API_KEY or enable USE_MCP_SAMPLING from an MCP client",
        }

    try:
        result = run_verification(
            spec_text,
            code_file,
            config=config,
            language=language,
            use_llm=use_llm,
            run_mumei=run_mumei,
            llm_provider=llm_provider,
        )
    except Exception as exc:
        return {"status": "error", "error": f"verify_code_spec_traceability failed: {exc}"}
    payload = asdict(result)
    payload["status"] = "ok" if result.success else "needs_review"
    return payload

@mcp.tool()
def verify_foreign_code(
    source_code: str,
    language: str,
    use_llm: bool = True,
    run_mumei: bool = True,
    ctx: Context | None = None,
) -> str:
    """Infer and verify contracts from existing code (Python, Rust, TypeScript, Go, Solidity)."""
    return _validate_existing_code_payload(
        source_code,
        language,
        use_llm=use_llm,
        run_mumei=run_mumei,
        tool_name="verify_foreign_code",
        ctx=ctx,
    )

@mcp.tool()
def audit_code(
    source_code: str,
    language: str,
    domain_hint: str = "",
    ctx: Context | None = None,
) -> dict:
    """Audit existing code for bugs by extracting specs and verifying them."""
    with telemetry.start_tool_span(
        "audit_code", carrier=_carrier_from_ctx(ctx), **{"mumei.language": language},
    ):
        try:
            from agent.audit import AuditPipeline
            from agent.config import AgentConfig
        except Exception as exc:  # pragma: no cover - defensive
            return {"success": False, "errors": [f"failed to import audit pipeline: {exc}"]}

        try:
            config = AgentConfig()
            llm_provider = _llm_provider_for_context(config, ctx)
            client = None if llm_provider is not None else _llm_client_for_context(config, ctx)
        except Exception:
            config = None
            llm_provider = None
            client = None

        try:
            result = AuditPipeline(
                config=config, client=client, llm_provider=llm_provider,
            ).audit_source(
                source_code,
                language,
                domain_hint=domain_hint,
            )
        except Exception as exc:
            return {"success": False, "errors": [f"audit_code failed: {exc}"]}
        return asdict(result)

@mcp.tool()
def suggest_mm_migration(code_file: str, language: str, issues_json: str = "[]") -> str:
    """Generate .mm migration skeletons for functions with verification issues.

    Args:
        code_file: Path to source code file.
        language: Source language (python/rust/typescript/go/solidity).
        issues_json: JSON array of issues from validate_foreign_code or verify_foreign_code.

    Returns:
        JSON with migration_hints[] containing function_name, priority, reason,
        skeleton, next_step.
    """
    try:
        from agent.mm_migration_advisor import suggest_migration_for_file
    except Exception as exc:  # pragma: no cover - defensive
        return _err(f"failed to import migration advisor: {exc}")

    source_path = Path(code_file).expanduser().resolve()
    if not source_path.is_file():
        return _err(f"code_file does not exist: {source_path}")

    try:
        issues = json.loads(issues_json)
    except json.JSONDecodeError as exc:
        return _err(f"failed to parse issues_json: {exc}")
    if not isinstance(issues, list):
        return _err("issues_json must be a JSON array")

    try:
        hints = suggest_migration_for_file(
            str(source_path),
            language,
            {"issues": issues},
        )
    except ValueError as exc:
        return _err(str(exc))
    except OSError as exc:
        return _err(f"failed to read code_file: {exc}")
    return _ok({"migration_hints": [asdict(hint) for hint in hints]})

@mcp.tool()
def scan_and_fix(
    code_file: str,
    language: str,
    spec: str = "",
    auto_heal: bool = False,
    heal_output_dir: str = "",
    domain_hint: str = "",
    output_format: str = "json",
    ctx: Context | None = None,
) -> dict:
    """
    Same contract as `mumei-agent audit --code-file ... --auto-migrate --auto-heal`.

    Steps:
    1. audit: extract spec, check health, verify contracts, emit spec_health_issues,
       verification_violations, verification_status, cross_validation_gaps, and next_steps
    2. migrate-suggest: generate migration_hints and .mm skeletons for functions with issues
    3. (optional) heal: run self-healing loop on each skeleton, recording healed_files
       and heal_errors

    Args:
        code_file: Path to the source code file or directory.
        language: Source language (python/rust/typescript/go/solidity).
        spec: Optional path to a natural-language spec file for validate-spec-to-code.
        auto_heal: If True, run the self-healing loop on generated .mm skeletons.
        heal_output_dir: Directory to write healed .mm files.
        domain_hint: Optional domain hint for spec extraction.
        output_format: json, human, or markdown formatted_report sidecar.
    """
    with telemetry.start_tool_span(
        "scan_and_fix",
        carrier=_carrier_from_ctx(ctx),
        **{"mumei.language": language, "mumei.auto_heal": auto_heal},
    ):
        from agent.audit import (
            AUDIT_CONTRACT_TERMS,
            AUDIT_SCHEMA_KEYS,
            AuditPipeline,
        )
        from agent.config import AgentConfig

        try:
            config = AgentConfig()
            llm_provider = _llm_provider_for_context(config, ctx)
            client = None if llm_provider is not None else _llm_client_for_context(config, ctx)
        except Exception:
            config = None
            llm_provider = None
            client = None

        pipeline = AuditPipeline(
            config=config, heal_output_dir=heal_output_dir or None, client=client,
            llm_provider=llm_provider,
        )
        code_path = Path(code_file).expanduser().resolve()
        if code_path.is_dir():
            result = pipeline.audit_directory(
                code_file,
                language,
                domain_hint=domain_hint,
                auto_migrate=True,
                auto_heal=auto_heal,
            )
        else:
            result = pipeline.audit_file(
                code_file,
                language,
                domain_hint=domain_hint,
                auto_migrate=True,
                auto_heal=auto_heal,
            )

        spec_alignment = None
        conformance_verification = None
        if spec and not code_path.is_dir():
            from agent.cross_validation import validate_spec_to_code as cv_validate_spec_to_code
            from agent.conformance_verifier import verify_conformance as cv_verify_conformance

            spec_text = Path(spec).read_text(encoding="utf-8")
            alignment = cv_validate_spec_to_code(
                spec_text, code_file, language=language,
                config=config, llm_provider=llm_provider,
            )
            spec_alignment = asdict(alignment)
            conformance = cv_verify_conformance(
                spec_text,
                code_file,
                language=language,
                alignment=alignment,
                config=config,
                llm_provider=llm_provider,
            )
            conformance_verification = asdict(conformance)
            if not conformance_verification.get("report"):
                from agent.report_formatter import format_result_report

                conformance_verification["report"] = format_result_report(conformance, "human")

        payload = {
            "audit": asdict(result),
            "next_steps": result.next_steps,
            "spec_alignment": spec_alignment,
            "conformance_verification": conformance_verification,
            "audit_schema": AUDIT_SCHEMA_KEYS,
            "contract_terms": AUDIT_CONTRACT_TERMS,
        }
        for key in AUDIT_SCHEMA_KEYS:
            default: object = None if key == "verification_status" else []
            payload[key] = getattr(result, key, default)
        if output_format in {"human", "markdown"}:
            from agent.report_formatter import format_scan_and_fix_report

            payload["formatted_report"] = format_scan_and_fix_report(payload)
        return payload

@mcp.tool()
def extract_spec_from_code(
    code_file: str,
    language: str = "",
    domain_hint: str = "",
    generate: bool = False,
    mumei_repo: str = "",
    ctx: Context | None = None,
) -> str:
    """Extract a Mumei forge task spec from an existing source-code path.

    Args:
        code_file: Path to a source-code file or directory.
        language: Optional language override. If omitted, extension and
            source-content heuristics are used.
        domain_hint: Optional domain hint for forge task extraction.
        generate: When true, also generate and verify Mumei code.
        mumei_repo: Path to mumei repo, used to prefer repo-local mumei
            binaries when generate=true.

    Returns:
        JSON string with the extracted natural-language spec, detected
        language, forge task spec, warnings, and optional generation result.
    """
    with telemetry.start_tool_span(
        "extract_spec_from_code", carrier=_carrier_from_ctx(ctx),
        **{"mcp.tool.generate": generate},
    ):
        source_path = Path(code_file).expanduser().resolve()
        if not source_path.exists():
            return _err(f"code_file does not exist: {source_path}")

        try:
            from agent.code_to_spec import CodeToSpecExtractor, Language
            from agent.config import AgentConfig
            from agent.extract_spec import extract_spec_from_code_directory
            from agent.mumei_client import create_mumei_client
        except Exception as exc:  # pragma: no cover - defensive
            return _err(f"failed to import agent modules: {exc}")

        if not source_path.is_file() and not source_path.is_dir():
            return _err(f"code_file is not a file or directory: {source_path}")

        selected_language: Language | None
        if language:
            allowed = set(CodeToSpecExtractor.EXTENSION_MAP.values()) | {"unknown"}
            if language not in allowed:
                return _err(
                    f"unsupported language: {language}",
                    supported_languages=sorted(allowed),
                )
            selected_language = language  # type: ignore[assignment]
        else:
            selected_language = None

        try:
            config = AgentConfig()
            llm_provider = _llm_provider_for_context(config, ctx)
            llm_client = None if llm_provider is not None else _llm_client_for_context(config, ctx)
            mumei_bin = config.mumei_bin
            if generate and mumei_repo:
                repo = _resolve_repo(mumei_repo)
                if not repo.exists():
                    return _err(f"mumei_repo does not exist: {repo}")
                release_bin = repo / "target" / "release" / "mumei"
                debug_bin = repo / "target" / "debug" / "mumei"
                if release_bin.exists():
                    mumei_bin = str(release_bin)
                elif debug_bin.exists():
                    mumei_bin = str(debug_bin)
            mumei = create_mumei_client(mumei_bin)
            if source_path.is_dir():
                payload = extract_spec_from_code_directory(
                    config,
                    source_path,
                    language=selected_language,
                    domain_hint=domain_hint,
                    mumei_client=mumei,
                    max_retries=config.max_retries,
                    client=llm_client, llm_provider=llm_provider,
                )
                forge_task_spec = payload["merged_spec"]
                result = None
            else:
                result = CodeToSpecExtractor(
                    config, client=llm_client, llm_provider=llm_provider,
                ).extract_from_file(
                    source_path,
                    language=selected_language,
                    domain_hint=domain_hint,
                    mumei_client=mumei,
                )
                payload = {
                    "natural_language_spec": result.natural_language_spec,
                    "detected_language": result.detected_language,
                    "spec": result.forge_task_spec,
                    "warnings": result.warnings,
                }
                forge_task_spec = result.forge_task_spec
        except Exception as exc:
            return _err(
                f"extract_spec_from_code failed: {exc}",
                hint="set LLM_API_KEY / OPENAI_API_KEY or enable USE_MCP_SAMPLING from an MCP client",
            )

        if result is not None and (not result.success or result.forge_task_spec is None):
            return _err(
                "code-to-spec extraction failed",
                natural_language_spec=result.natural_language_spec,
                detected_language=result.detected_language,
                warnings=result.warnings,
                errors=result.errors,
            )

        if generate:
            try:
                from agent.generate import _normalize_forge_task_spec
                from agent.strategies.generate_strategy import generate_code
                from agent.strategies.spec_refinement import run_refinement_loop

                code, verified, final_spec = run_refinement_loop(
                    llm_client,
                    config.model,
                    _normalize_forge_task_spec(forge_task_spec),
                    generate_code,
                    max_refinements=3,
                    config_max_retries=config.max_retries,
                    mumei_client=mumei,
                )
                payload.update(
                    {"code": code, "verified": verified, "final_spec": final_spec}
                )
            except Exception as exc:
                return _err(
                    f"generation failed after code-to-spec extraction: {exc}",
                    **payload,
                )

        return _ok(payload)

def main() -> None:
    """Run the FastMCP server over stdio.

    Used by ``python -m agent mcp-server`` and by MCP client configs
    that spawn the agent as a subprocess.
    """
    logging.basicConfig(level=logging.INFO)
    mcp.run()

if __name__ == "__main__":
    main()
