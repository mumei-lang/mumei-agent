"""LLM model-quality benchmark for the forge pipeline.

This test exercises ``agent.strategies.generate_strategy.generate_code``
against a low-difficulty reference task (``forge_tasks/vstd_math_abs.json``)
and records per-model success rate, average generated-code length, and
wall-clock time.  Results are written as JSON so multiple runs can be
compared across different ``LLM_MODEL`` settings.

The test is marked with ``@pytest.mark.benchmark`` and is **skipped by
default**.  Opt in explicitly with:

    pytest -m benchmark tests/test_llm_benchmark.py

Because a real LLM endpoint is required, the test also auto-skips when no
credentials are available in the environment (neither ``LLM_API_KEY`` nor
``OPENAI_API_KEY``).  Set ``LLM_BENCHMARK_MODELS`` to a comma-separated
list of models to benchmark (for example
``gpt-4o-mini,qwen-plus,qwen2.5-coder:7b``), and optionally
``LLM_BENCHMARK_TRIALS`` (default ``3``) to change how many trials each
model gets.

The companion ``.github/workflows/proliferate.yml`` documents recommended
models and their quality/cost trade-offs for operators selecting a
``llm_model`` value.
"""
from __future__ import annotations

import json
import os
import statistics
import time
from pathlib import Path
from typing import Any

import pytest

from agent.forge_discovery import discover_tasks

REPO_ROOT = Path(__file__).resolve().parent.parent
FORGE_TASKS_DIR = REPO_ROOT / "forge_tasks"
REFERENCE_TASK_ID = "vstd-math-abs"
DEFAULT_TRIALS = 3
DEFAULT_MODELS = ("gpt-4o-mini",)

_API_KEY_ENV_VARS = ("LLM_API_KEY", "OPENAI_API_KEY")


def _has_llm_credentials() -> bool:
    return any(os.environ.get(var) for var in _API_KEY_ENV_VARS)


def _resolve_models() -> list[str]:
    raw = os.environ.get("LLM_BENCHMARK_MODELS", "")
    if not raw.strip():
        return list(DEFAULT_MODELS)
    return [m.strip() for m in raw.split(",") if m.strip()]


def _resolve_trials() -> int:
    raw = os.environ.get("LLM_BENCHMARK_TRIALS", "")
    if not raw.strip():
        return DEFAULT_TRIALS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_TRIALS
    return max(1, value)


def _load_reference_task() -> dict[str, Any]:
    tasks = discover_tasks(FORGE_TASKS_DIR)
    for task in tasks:
        if task.get("task_id") == REFERENCE_TASK_ID:
            return task
    raise RuntimeError(
        f"reference task {REFERENCE_TASK_ID!r} not found in {FORGE_TASKS_DIR}"
    )


def _task_to_generate_spec(task: dict[str, Any]) -> dict[str, Any]:
    """Flatten a forge task spec into the single-atom shape generate_code expects."""
    atoms = task.get("atoms") or []
    if not atoms:
        raise RuntimeError(f"task {task.get('task_id')!r} has no atoms")
    atom = atoms[0]
    return {
        "name": atom.get("name", task.get("task_id", "benchmark_atom")),
        "description": atom.get("description", task.get("description", "")),
        "inputs": atom.get("inputs", []),
        "return_type": atom.get("return_type", "i64"),
        "requires": atom.get("requires", "true"),
        "ensures": atom.get("ensures", "true"),
        "reference_patterns": atom.get("reference_patterns", []),
        "module_name": task.get("target_file", "std/benchmark.mm"),
    }


def _run_single_trial(model: str, spec: dict[str, Any]) -> dict[str, Any]:
    """Run a single generate_code trial and report its outcome.

    Returns a dict with keys ``success`` (bool), ``code_length`` (int),
    and ``duration_seconds`` (float).  Never raises — failures are
    captured in the ``error`` field so a noisy model doesn't abort the
    whole benchmark.

    ``generate_code`` returns a ``tuple[str, bool]`` of
    ``(code, verified)``; retry count is not exposed by the public API
    so we only report the success bit here.
    """
    from agent.config import AgentConfig
    from agent.strategies.generate_strategy import generate_code

    os.environ["LLM_MODEL"] = model

    cfg = AgentConfig()
    cfg.model = model
    client = cfg.create_client()

    start = time.monotonic()
    success = False
    code_length = 0
    error: str | None = None
    try:
        code, verified = generate_code(
            client=client,
            model=cfg.model,
            spec=spec,
            config_max_retries=cfg.max_retries,
            mumei_client=None,
        )
        success = bool(verified)
        code_length = len(code or "")
    except Exception as exc:  # noqa: BLE001 — benchmark should swallow all
        error = f"{type(exc).__name__}: {exc}"
    duration = time.monotonic() - start

    out: dict[str, Any] = {
        "success": success,
        "code_length": code_length,
        "duration_seconds": round(duration, 3),
    }
    if error is not None:
        out["error"] = error
    return out


def _summarise(model: str, trials: list[dict[str, Any]]) -> dict[str, Any]:
    successes = [t for t in trials if t["success"]]
    durations = [t["duration_seconds"] for t in trials]
    code_lengths = [t["code_length"] for t in trials]
    return {
        "model": model,
        "trials": len(trials),
        "success_rate": round(len(successes) / len(trials), 3) if trials else 0.0,
        "avg_code_length": round(statistics.mean(code_lengths), 1) if code_lengths else 0.0,
        "avg_time_seconds": round(statistics.mean(durations), 3) if durations else 0.0,
        "details": trials,
    }


@pytest.mark.benchmark
def test_llm_model_benchmark(tmp_path: Path) -> None:
    """Benchmark generate_code across one or more LLM models.

    Skipped by default; opt in with ``pytest -m benchmark``.  Also
    auto-skipped when no LLM credentials are available so CI remains
    green without exposing API keys.
    """
    if not _has_llm_credentials():
        pytest.skip(
            "no LLM credentials in environment "
            f"({' or '.join(_API_KEY_ENV_VARS)}); benchmark requires a real endpoint"
        )

    task = _load_reference_task()
    spec = _task_to_generate_spec(task)
    models = _resolve_models()
    trials = _resolve_trials()

    results = []
    for model in models:
        per_model: list[dict[str, Any]] = []
        for _ in range(trials):
            per_model.append(_run_single_trial(model, spec))
        results.append(_summarise(model, per_model))

    out_path = Path(os.environ.get("LLM_BENCHMARK_OUTPUT") or (tmp_path / "llm_benchmark.json"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "reference_task": task.get("task_id"),
                "results": results,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # Sanity: every benchmarked model must produce at least one trial entry.
    assert results, "no benchmark results were collected"
    for entry in results:
        assert entry["trials"] == trials, entry
