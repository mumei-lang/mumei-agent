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

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("Mumei-Agent")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _err(message: str, **extra: Any) -> str:
    """Return a JSON-encoded error payload."""
    payload: dict[str, Any] = {"status": "error", "error": message}
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)


def _ok(payload: dict[str, Any]) -> str:
    """Return a JSON-encoded ``status: ok`` payload."""
    payload.setdefault("status", "ok")
    return json.dumps(payload, ensure_ascii=False, default=str)


def _resolve_repo(path: str) -> Path:
    """Resolve *path* as an absolute Path."""
    return Path(path).expanduser().resolve()


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def forge_task(task_json: str, mumei_repo: str, dry_run: bool = True) -> str:
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
    try:
        task = json.loads(task_json)
    except json.JSONDecodeError as exc:
        return _err(f"task_json is not valid JSON: {exc}")
    if not isinstance(task, dict):
        return _err("task_json must decode to a JSON object")

    repo = _resolve_repo(mumei_repo)
    if not repo.exists():
        return _err(f"mumei_repo does not exist: {repo}")

    # Lazy imports keep the module importable in environments without the
    # OpenAI client (e.g. the tools-only CI used by the unit tests).
    try:
        from agent.config import AgentConfig
        from agent.forge import MumeiForge
        from agent.mumei_client import MumeiClient
    except Exception as exc:  # pragma: no cover - defensive
        return _err(f"failed to import agent modules: {exc}")

    config: AgentConfig | None = None
    if not dry_run:
        try:
            config = AgentConfig()
            # Force eager validation so misconfigured callers fail fast
            # with a clear error instead of crashing inside the LLM call.
            config.create_client()
        except Exception as exc:
            return _err(
                f"AgentConfig is unavailable: {exc}",
                hint="set LLM_API_KEY (or run with dry_run=true)",
            )

    mumei_bin = (config.mumei_bin if config else None) or os.environ.get(
        "MUMEI_BIN", "mumei"
    )
    mumei_client = MumeiClient(mumei_bin)
    forge_tasks_dir = repo.parent / "mumei-agent" / "forge_tasks"
    if not forge_tasks_dir.exists():
        forge_tasks_dir = repo / "forge_tasks"

    forge = MumeiForge(
        config=config,
        mumei_client=mumei_client,
        mumei_repo_dir=repo,
        forge_tasks_dir=forge_tasks_dir,
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
def heal_file(source_code: str, error_report: str = "") -> str:
    """Self-heal mumei source code via the LLM-driven fix strategy.

    Args:
        source_code: The current ``.mm`` source code to repair.
        error_report: Optional verification error report to seed the
            prompt.  When omitted, the agent runs ``mumei verify`` first
            and uses the resulting report.

    Returns:
        JSON string with ``healed_code``, ``attempts``, ``success``,
        and ``error`` fields.  Requires :class:`agent.config.AgentConfig`
        to be configured (LLM_API_KEY etc.); errors out cleanly with a
        descriptive ``hint`` field otherwise.
    """
    if not source_code or not source_code.strip():
        return _err("source_code must be non-empty")

    try:
        from agent.config import AgentConfig
        from agent.mumei_client import MumeiClient
        from agent.strategies.fix_strategy import get_fix
    except Exception as exc:  # pragma: no cover - defensive
        return _err(f"failed to import agent modules: {exc}")

    try:
        config = AgentConfig()
        client = config.create_client()
    except Exception as exc:
        return _err(
            f"AgentConfig is unavailable: {exc}",
            hint="set LLM_API_KEY / OPENAI_API_KEY for heal_file",
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

        mumei = MumeiClient(config.mumei_bin)
        try:
            with tempfile.NamedTemporaryFile(
                "w", suffix=".mm", delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(source_code)
                tmp_path = tmp.name
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
            try:
                Path(tmp_path).unlink()
            except Exception:
                pass

    try:
        healed = get_fix(
            client=client,
            model=config.model,
            source_code=source_code,
            error_log=error_log or "",
            report_data=report_data,
            strategy=getattr(config, "strategy", "single"),
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
def measure_std_health(mumei_repo: str) -> str:
    """Measure proof-health metrics for the mumei std/ library.

    Delegates to :func:`agent.std_health.measure_health`.

    Returns:
        JSON string with ``total_files``, ``verified_files``,
        ``failed_files``, ``total_atoms``, ``verified_atoms``,
        ``trusted_atoms``, ``health_score``, ``todo_count``, and
        ``details``.
    """
    repo = _resolve_repo(mumei_repo)
    std_dir = repo / "std"
    if not std_dir.exists():
        return _err(f"std directory not found under {repo}")

    try:
        from agent.config import AgentConfig
        from agent.mumei_client import MumeiClient
        from agent.std_health import measure_health
    except Exception as exc:  # pragma: no cover - defensive
        return _err(f"failed to import agent modules: {exc}")

    try:
        config = AgentConfig()
        mumei_bin = config.mumei_bin
    except Exception:
        mumei_bin = os.environ.get("MUMEI_BIN", "mumei")

    mumei_client = MumeiClient(mumei_bin)
    try:
        report = measure_health(mumei_client, std_dir)
    except Exception as exc:
        return _err(f"measure_health raised: {exc}")

    payload = dict(report)
    return _ok(payload)


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
def get_agent_status() -> str:
    """Return information about the running mumei-agent installation.

    Useful for external agents (Claude Code, Devin, ...) that want to
    introspect what they can do before issuing tool calls.

    Returns:
        JSON string with the LLM provider/model, mumei binary path,
        available CLI subcommands, registered MCP tools, and the
        relevant feature-flag environment variables.
    """
    try:
        from agent.config import AgentConfig
    except Exception as exc:  # pragma: no cover - defensive
        return _err(f"failed to import agent.config: {exc}")

    try:
        config = AgentConfig()
    except Exception as exc:  # pragma: no cover - defensive
        return _err(f"AgentConfig() failed: {exc}")

    # Hard-coded mirror of ``agent.__main__._SUBCOMMANDS`` — importing
    # ``agent.__main__`` would execute its top-level ``main()`` call.
    subcommands = sorted(
        {
            "heal",
            "generate",
            "publish",
            "forge",
            "propose",
            "proliferate",
            "health",
            "mcp-server",
        }
    )

    return _ok(
        {
            "llm_provider": "openai-compatible",
            "model": config.model,
            "base_url": config.base_url,
            "mumei_bin": config.mumei_bin,
            "strategy": config.strategy,
            "subcommands": subcommands,
            "mcp_tools": [
                "forge_task",
                "heal_file",
                "measure_std_health",
                "propose_forge_tasks",
                "list_forge_log",
                "get_agent_status",
            ],
            "feature_flags": {
                "PREFER_MCP_GAPS": os.environ.get("PREFER_MCP_GAPS", ""),
                "USE_MCP_CLIENT": os.environ.get("USE_MCP_CLIENT", ""),
                "INJECT_CORE_AXIOMS": os.environ.get("INJECT_CORE_AXIOMS", ""),
            },
            "python": sys.version,
        }
    )


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the FastMCP server over stdio.

    Used by ``python -m agent mcp-server`` and by MCP client configs
    that spawn the agent as a subprocess.
    """
    logging.basicConfig(level=logging.INFO)
    mcp.run()


if __name__ == "__main__":
    main()
