"""Mumei Forge Mode: autonomous std-library expansion.

The forge mode iterates over task specifications in a directory,
invokes the existing ``generate_code()`` pipeline to produce verified
atoms, appends (or creates/replaces) the target `.mm` files, and
optionally commits each successful forge to git.

This is the orchestration layer.  It deliberately re-uses the
lower-level building blocks:

- ``agent.strategies.generate_strategy.generate_code`` for
  LLM-driven atom generation + self-healing
- ``agent.strategies.retry_history.RetryHistory.is_same_error_repeating``
  for same-error-skip detection
- ``agent.publish._git`` for git interaction
"""
from __future__ import annotations

import datetime
import fcntl
import json
import logging
import re
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from openai import OpenAI

from agent.config import AgentConfig
from agent.mumei_client import MumeiClient, create_mumei_client
from agent.forge_discovery import discover_tasks, filter_completed_tasks
from agent.harness_metrics import HarnessMetrics, harness_profile_names
from agent.llm_provider import LLMProvider, complete_text
from agent.metrics import (
    Metrics,
    decidable_fragment_tags_from_verify_result,
    metrics_quarter,
)
from agent.prompts.forge.forge_append import build_append_prompt
from agent.prompts.forge.forge_system import FORGE_SYSTEM_PROMPT
from agent.prompts.report_formatter import (
    format_actionable_fix_hint,
    format_counterexample,
    format_structured_unsat_core,
)
from agent.publish import _ensure_git_identity, _git
from agent.strategies.generate_strategy import (
    _extract_code,  # type: ignore[attr-defined]
    generate_code,
)

_logger = logging.getLogger(__name__)

_CODE_FENCE_RE = re.compile(r"```\w*\s*\n(.*?)```", re.DOTALL)

# Characters allowed in task_ids / target paths when used in commit messages.
_SAFE_TASK_ID_RE = re.compile(r"^[A-Za-z0-9._\-]+$")


def _render_deterministic_atom(atom: dict[str, Any]) -> list[str]:
    name = str(atom.get("name", "generated_atom"))
    params = atom.get("inputs") or atom.get("params") or []
    param_text = ", ".join(
        f"{param.get('name', 'arg')}: {param.get('type', 'i64')}"
        for param in params
        if isinstance(param, dict)
    )
    requires = str(atom.get("requires", "true"))
    ensures = str(atom.get("ensures", "true"))
    body = str(atom.get("body") or atom.get("body_expr") or "0").strip()
    lines: list[str] = [f"// --- {name} ---"]
    lines.extend(
        [
            f"atom {name}({param_text})",
            f"    requires: {requires};",
            f"    ensures: {ensures};",
            "    body: {",
        ]
    )
    for body_line in body.splitlines():
        lines.append(f"        {body_line.strip()}")
    lines.append("    };")
    return lines


def _count_mapping(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    counts: dict[str, int] = {}
    for key, raw_count in value.items():
        if isinstance(key, str):
            try:
                counts[key] = int(raw_count)
            except (TypeError, ValueError):
                counts[key] = 0
    return counts


def _merge_counts(target: dict[str, int], source: dict[str, int]) -> None:
    for key, count in source.items():
        target[key] = target.get(key, 0) + count


def _success_counts_by_reason(
    value: Any,
    by_reason: dict[str, int],
    lean_successes: int,
) -> dict[str, int]:
    successes_by_reason = _count_mapping(value)
    if successes_by_reason:
        return successes_by_reason
    if len(by_reason) == 1:
        reason, attempts = next(iter(by_reason.items()))
        return {reason: min(lean_successes, attempts)}
    return {}


def _low_success_categories(
    by_reason: dict[str, int],
    successes_by_reason: dict[str, int],
) -> list[str]:
    categories = [
        reason
        for reason, attempts in by_reason.items()
        if attempts > 0 and successes_by_reason.get(reason, 0) / attempts < 0.5
    ]
    return sorted(categories)


def collect_escalation_metrics(bundle_path: str) -> dict[str, Any]:
    bundle = json.loads(Path(bundle_path).read_text(encoding="utf-8"))
    summary = bundle.get("summary", {})
    if not isinstance(summary, dict):
        summary = {}
    candidates = bundle.get("candidates", [])
    if not isinstance(candidates, list):
        candidates = []

    by_reason = _count_mapping(summary.get("by_reason"))
    by_logic_fragment = _count_mapping(summary.get("by_logic_fragment"))
    lean_successes = 0
    successes_by_reason: dict[str, int] = {}
    partial_translation = 0
    manual_required = 0

    if candidates:
        by_reason = {}
        by_logic_fragment = {}
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            reason = candidate.get("escalation_reason")
            if isinstance(reason, str):
                by_reason[reason] = by_reason.get(reason, 0) + 1
            tags = candidate.get("logic_fragment_tags", [])
            if isinstance(tags, list):
                for tag in tags:
                    if isinstance(tag, str):
                        by_logic_fragment[tag] = by_logic_fragment.get(tag, 0) + 1
            lean_metadata = candidate.get("lean_metadata")
            status = lean_metadata.get("status") if isinstance(lean_metadata, dict) else None
            if status == "lean_verified":
                lean_successes += 1
                if isinstance(reason, str):
                    successes_by_reason[reason] = successes_by_reason.get(reason, 0) + 1
            elif status == "partial_translation":
                partial_translation += 1
            elif candidate.get("manual_lemma_reason") is not None:
                manual_required += 1

    candidate_count = int(summary.get("candidate_count", len(candidates)) or 0)
    total_atoms = int(summary.get("total_atoms", 0) or 0)
    if not candidates:
        lean_successes = int(summary.get("lean_successes", 0) or 0)
        successes_by_reason = _success_counts_by_reason(
            summary.get("successes_by_failure_reason"),
            by_reason,
            lean_successes,
        )
    success_rate = lean_successes / candidate_count if candidate_count else 0.0
    return {
        "total_atoms": total_atoms,
        "candidate_count": candidate_count,
        "escalation_attempts": candidate_count,
        "lean_successes": lean_successes,
        "partial_translation": partial_translation,
        "manual_required": manual_required,
        "success_rate": success_rate,
        "by_reason": by_reason,
        "by_failure_reason": by_reason,
        "successes_by_failure_reason": successes_by_reason,
        "by_logic_fragment": by_logic_fragment,
        "low_success_categories": _low_success_categories(by_reason, successes_by_reason),
    }


def track_escalation_trends(metrics_history: list[dict[str, Any]]) -> dict[str, Any]:
    quarters: dict[str, dict[str, Any]] = {}
    aggregate_by_reason: dict[str, int] = {}
    aggregate_by_logic_fragment: dict[str, int] = {}
    aggregate_successes_by_reason: dict[str, int] = {}
    aggregate_attempts = 0
    aggregate_successes = 0
    aggregate_partial_translation = 0
    aggregate_manual_required = 0

    for metrics in metrics_history:
        quarter = str(
            metrics.get("quarter")
            or metrics.get("metrics_quarter")
            or metrics_quarter()
        )
        quarter_metrics = quarters.setdefault(
            quarter,
            {
                "escalation_attempts": 0,
                "lean_successes": 0,
                "partial_translation": 0,
                "manual_required": 0,
                "by_reason": {},
                "successes_by_failure_reason": {},
                "by_logic_fragment": {},
                "low_success_categories": [],
            },
        )
        attempts = int(metrics.get("escalation_attempts", metrics.get("candidate_count", 0)) or 0)
        successes = int(metrics.get("lean_successes", 0) or 0)
        partial = int(metrics.get("partial_translation", 0) or 0)
        manual = int(metrics.get("manual_required", 0) or 0)
        by_reason = _count_mapping(
            metrics.get("by_failure_reason", metrics.get("by_reason", {}))
        )
        by_logic_fragment = _count_mapping(metrics.get("by_logic_fragment"))
        successes_by_reason = _success_counts_by_reason(
            metrics.get("successes_by_failure_reason"),
            by_reason,
            successes,
        )

        quarter_metrics["escalation_attempts"] += attempts
        quarter_metrics["lean_successes"] += successes
        quarter_metrics["partial_translation"] += partial
        quarter_metrics["manual_required"] += manual
        _merge_counts(quarter_metrics["by_reason"], by_reason)
        _merge_counts(quarter_metrics["successes_by_failure_reason"], successes_by_reason)
        _merge_counts(quarter_metrics["by_logic_fragment"], by_logic_fragment)

        aggregate_attempts += attempts
        aggregate_successes += successes
        aggregate_partial_translation += partial
        aggregate_manual_required += manual
        _merge_counts(aggregate_by_reason, by_reason)
        _merge_counts(aggregate_successes_by_reason, successes_by_reason)
        _merge_counts(aggregate_by_logic_fragment, by_logic_fragment)

    for quarter_metrics in quarters.values():
        attempts = quarter_metrics["escalation_attempts"]
        successes = quarter_metrics["lean_successes"]
        partial = quarter_metrics["partial_translation"]
        quarter_metrics["success_rate"] = successes / attempts if attempts else 0.0
        quarter_metrics["partial_translation_rate"] = partial / attempts if attempts else 0.0
        quarter_metrics["low_success_categories"] = _low_success_categories(
            quarter_metrics["by_reason"],
            quarter_metrics["successes_by_failure_reason"],
        )

    return {
        "quarters": dict(sorted(quarters.items())),
        "overall": {
            "escalation_attempts": aggregate_attempts,
            "lean_successes": aggregate_successes,
            "partial_translation": aggregate_partial_translation,
            "manual_required": aggregate_manual_required,
            "success_rate": aggregate_successes / aggregate_attempts if aggregate_attempts else 0.0,
            "partial_translation_rate": (
                aggregate_partial_translation / aggregate_attempts if aggregate_attempts else 0.0
            ),
            "by_reason": aggregate_by_reason,
            "successes_by_failure_reason": aggregate_successes_by_reason,
            "by_logic_fragment": aggregate_by_logic_fragment,
            "low_success_categories": _low_success_categories(
                aggregate_by_reason,
                aggregate_successes_by_reason,
            ),
        },
    }


@dataclass
class ForgeResult:
    """Outcome of forging a single task."""

    task_id: str
    status: str  # "success" | "failed" | "skipped"
    attempts: int = 0
    target_file: str | None = None
    atoms_added: list[str] = field(default_factory=list)
    logic_fragment_tags: list[str] = field(default_factory=list)
    outside_decidable_fragment: bool = False
    metrics_quarter: str | None = None
    commit_sha: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MumeiForge:
    """Orchestrator for the autonomous forge pipeline."""

    def __init__(
        self,
        config: AgentConfig | None,
        mumei_client: MumeiClient,
        mumei_repo_dir: Path,
        forge_tasks_dir: Path,
        *,
        log_path: Path | None = None,
        openai_client: OpenAI | LLMProvider | None = None,
        llm_provider: LLMProvider | None = None,
        harness_metrics: HarnessMetrics | None = None,
    ) -> None:
        # ``config`` may be ``None`` for dry-run usage, where the forge
        # only discovers/prints tasks and never calls the LLM or
        # commits.  Methods that actually need the config will raise
        # via :meth:`_ensure_openai_client` / :meth:`_commit_change`.
        self.config = config
        self.mumei = mumei_client
        self.mumei_repo_dir = Path(mumei_repo_dir).resolve()
        self.forge_tasks_dir = Path(forge_tasks_dir).resolve()
        self.log_path = Path(log_path) if log_path else self.forge_tasks_dir.parent / "forge_log.json"
        self.metrics_path = self.log_path.with_name("p8_decidable_metrics.json")
        self._client: OpenAI | LLMProvider | None = openai_client
        self._llm_provider = llm_provider
        self.harness_metrics = harness_metrics or HarnessMetrics.from_profile("basic")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        *,
        max_tasks: int | None = None,
        dry_run: bool = False,
        auto_commit_override: bool | None = None,
        max_retries_override: int | None = None,
        single_task_path: Path | None = None,
    ) -> list[ForgeResult]:
        """Run the forge pipeline over all discovered tasks.

        Parameters
        ----------
        max_tasks:
            Upper bound on the number of tasks to execute.
        dry_run:
            When true, print the execution plan and return without
            generating or committing anything.
        auto_commit_override:
            When not ``None``, override each task's ``auto_commit`` flag.
        max_retries_override:
            When not ``None``, override each task's ``max_retries``.
        single_task_path:
            When provided, run only this specific spec file.
        """
        if single_task_path is not None:
            tasks = self._load_single_task(single_task_path)
        else:
            tasks = discover_tasks(self.forge_tasks_dir)
            tasks = filter_completed_tasks(tasks, self.log_path)

        if max_tasks is not None:
            tasks = tasks[:max_tasks]

        tasks = [self.harness_metrics.apply_to_spec(task) for task in tasks]

        if dry_run:
            self._print_plan(tasks)
            return [
                ForgeResult(
                    task_id=t.get("task_id", "unknown"),
                    status="skipped",
                    target_file=t.get("target_file"),
                    error="dry-run",
                )
                for t in tasks
            ]

        results: list[ForgeResult] = []
        for task in tasks:
            if auto_commit_override is not None:
                task = {**task, "auto_commit": auto_commit_override}
            if max_retries_override is not None:
                task = {**task, "max_retries": max_retries_override}
            result = self.forge_one(task)
            self.log_result(task, result)
            results.append(result)
        return results

    def forge_one(self, task: dict[str, Any]) -> ForgeResult:
        """Forge a single task end-to-end."""
        task_id = task.get("task_id", "unknown")
        target_rel = task.get("target_file")
        mode = task.get("mode", "append")
        atoms = task.get("atoms") or []
        max_retries = int(task.get("max_retries", 5))

        if not target_rel:
            return ForgeResult(
                task_id=task_id, status="failed",
                error="task has no target_file",
            )
        if not atoms:
            return ForgeResult(
                task_id=task_id, status="failed", target_file=target_rel,
                error="task has no atoms",
            )

        target_path = (self.mumei_repo_dir / target_rel).resolve()
        try:
            target_path.relative_to(self.mumei_repo_dir)
        except ValueError:
            return ForgeResult(
                task_id=task_id, status="failed", target_file=target_rel,
                error=f"target_file escapes repo root: {target_rel}",
            )

        _logger.info("Forging task %s -> %s (mode=%s)", task_id, target_rel, mode)

        # Snapshot the pre-forge file state so we can restore it on any
        # failure path below (including a post-write verify failure).
        # This prevents:
        #   - create mode tasks becoming permanently stuck because the
        #     file now exists on retry;
        #   - replace mode losing the original file contents;
        #   - append mode duplicating atoms on retry when the outer
        #     verify passes inside _forge_append but the final sanity
        #     check at this layer fails.
        target_existed_before = target_path.exists()
        original_bytes: bytes | None = (
            target_path.read_bytes() if target_existed_before else None
        )

        def _restore_target() -> None:
            try:
                if target_existed_before and original_bytes is not None:
                    target_path.write_bytes(original_bytes)
                elif target_path.exists():
                    target_path.unlink()
            except OSError as restore_exc:
                _logger.warning(
                    "Failed to restore %s after forge failure: %s",
                    target_path, restore_exc,
                )

        generation_metrics = Metrics()
        try:
            if mode == "append":
                new_code, attempts = self._forge_append(
                    task,
                    target_path,
                    max_retries,
                    metrics=generation_metrics,
                )
            elif mode in {"create", "replace"}:
                new_code, attempts = self._forge_module(
                    task,
                    target_path,
                    mode,
                    max_retries,
                    metrics=generation_metrics,
                )
            else:
                return ForgeResult(
                    task_id=task_id, status="failed", target_file=target_rel,
                    error=f"unknown mode: {mode}",
                )
        except Exception as exc:
            _logger.exception("Forge task %s raised", task_id)
            _restore_target()
            return ForgeResult(
                task_id=task_id, status="failed", target_file=target_rel,
                error=f"{type(exc).__name__}: {exc}",
            )

        if not new_code:
            # _forge_append already restores on its own retry exhaustion,
            # but _forge_module may have left a partial write behind.
            _restore_target()
            self.harness_metrics.record_result(
                "forge_generation",
                False,
                retry_class="generation_failed",
                attempts=attempts,
                tokens_to_success=generation_metrics.llm_tokens_used,
                solver_seconds_to_success=sum(
                    generation_metrics.verification_times_seconds
                ),
            )
            return ForgeResult(
                task_id=task_id, status="failed", target_file=target_rel,
                attempts=attempts,
                error="generation or verification failed",
            )

        # Verify the full updated file before finalizing the change.
        verify_result = self.mumei.verify(
            str(target_path),
            collect_decidable_metrics=True,
        )
        logic_fragment_tags, metrics_quarter_key = self._record_decidable_fragment_metrics(
            verify_result,
            first_pass_verified=bool(verify_result.get("success", False)),
        )
        if not verify_result["success"]:
            _logger.warning(
                "Post-write verification failed for %s: %s",
                target_path, verify_result.get("stderr", "")[:200],
            )
            _restore_target()
            self.harness_metrics.record_result(
                "forge_post_write_verify",
                False,
                retry_class="post_write_verify_failed",
                attempts=attempts,
                tokens_to_success=generation_metrics.llm_tokens_used,
                solver_seconds_to_success=sum(
                    generation_metrics.verification_times_seconds
                ),
            )
            return ForgeResult(
                task_id=task_id, status="failed", target_file=target_rel,
                attempts=attempts, atoms_added=[a.get("name", "") for a in atoms],
                logic_fragment_tags=logic_fragment_tags,
                outside_decidable_fragment=bool(logic_fragment_tags),
                metrics_quarter=metrics_quarter_key,
                error="post-write verify failed",
            )

        atoms_added = [a.get("name", "") for a in atoms if a.get("name")]
        self.harness_metrics.record_result(
            "forge_post_write_verify",
            True,
            retry_class="none",
            attempts=attempts,
            tokens_to_success=generation_metrics.llm_tokens_used,
            solver_seconds_to_success=sum(
                generation_metrics.verification_times_seconds
            ),
        )

        commit_sha: str | None = None
        if bool(task.get("auto_commit", False)):
            commit_sha = self._commit_change(task, target_rel, atoms_added)

        return ForgeResult(
            task_id=task_id,
            status="success",
            attempts=attempts,
            target_file=target_rel,
            atoms_added=atoms_added,
            logic_fragment_tags=logic_fragment_tags,
            outside_decidable_fragment=bool(logic_fragment_tags),
            metrics_quarter=metrics_quarter_key,
            commit_sha=commit_sha,
        )

    # ------------------------------------------------------------------
    # Mode implementations
    # ------------------------------------------------------------------

    def _forge_append(
        self,
        task: dict[str, Any],
        target_path: Path,
        max_retries: int,
        *,
        metrics: Metrics | None = None,
    ) -> tuple[str, int]:
        """Generate new atoms and append them to an existing .mm file.

        Returns (combined_full_source, attempts).  Returns ("", attempts)
        when generation failed.
        """
        if not target_path.exists():
            raise FileNotFoundError(
                f"append mode requires existing target: {target_path}"
            )

        original_source = target_path.read_text(encoding="utf-8")
        attempts = 0
        last_error: str | None = None
        last_snippet: str | None = None

        for attempt in range(1, max_retries + 1):
            attempts = attempt
            snippet = self._generate_append_snippet(
                task, original_source,
                last_error=last_error, last_snippet=last_snippet,
                metrics=metrics,
            )
            if not snippet:
                continue

            combined = original_source.rstrip() + "\n\n" + snippet.strip() + "\n"
            target_path.write_text(combined, encoding="utf-8")

            check = self.mumei.check(str(target_path))
            if not check["success"]:
                last_error = (check.get("stdout", "") + check.get("stderr", "")).strip()
                last_snippet = snippet
                _logger.info(
                    "forge-append: parse check failed on attempt %d", attempt,
                )
                continue

            verify_started_at = datetime.datetime.now(datetime.timezone.utc)
            verify = self.mumei.verify(str(target_path))
            if metrics is not None:
                elapsed = (
                    datetime.datetime.now(datetime.timezone.utc) - verify_started_at
                ).total_seconds()
                metrics.record_verification_time(elapsed)
            if verify["success"]:
                return combined, attempts

            last_error = _enrich_error_with_report(
                (verify.get("stdout", "") + verify.get("stderr", "")).strip(),
                verify.get("report"),
            )
            last_snippet = snippet
            _logger.info(
                "forge-append: verify failed on attempt %d: %s",
                attempt, (verify.get("stderr") or "")[:120],
            )

        # All retries exhausted — restore original.
        target_path.write_text(original_source, encoding="utf-8")
        return "", attempts

    def _forge_module(
        self,
        task: dict[str, Any],
        target_path: Path,
        mode: str,
        max_retries: int,
        *,
        metrics: Metrics | None = None,
    ) -> tuple[str, int]:
        """Generate a whole module (create/replace mode) via generate_code()."""
        if mode == "create" and target_path.exists():
            raise FileExistsError(
                f"create mode requires a non-existent target: {target_path}"
            )

        deterministic_code = self._render_deterministic_module(task)
        if deterministic_code:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(deterministic_code, encoding="utf-8")
            return deterministic_code, 1

        spec = self._task_to_generate_spec(task)
        client = self._ensure_openai_client()

        code, verified = generate_code(
            client=client,
            model=self.config.model,
            spec=spec,
            config_max_retries=max_retries,
            mumei_client=self.mumei,
            metrics=metrics,
        )
        # ``generate_code`` does not expose its internal retry count, so
        # we can only report a lower bound (≥ 1 LLM call was made).
        # Reporting ``max_retries`` on failure would be wildly wrong when
        # the function exits early (e.g. empty LLM response).  The
        # append-mode path does expose its real attempt count via the
        # outer retry loop in ``_forge_append``.
        attempts = 1

        if not code or not verified:
            return "", attempts

        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(code, encoding="utf-8")
        return code, attempts

    # ------------------------------------------------------------------
    # LLM call for append mode
    # ------------------------------------------------------------------

    def _generate_append_snippet(
        self,
        task: dict[str, Any],
        existing_source: str,
        *,
        last_error: str | None = None,
        last_snippet: str | None = None,
        metrics: Metrics | None = None,
    ) -> str:
        """Ask the LLM to generate just the new atom(s) for append mode."""
        client = self._ensure_openai_client()

        cross_file_context = self._load_context_files(task)
        prompt = build_append_prompt(
            task, existing_source,
            last_error=last_error, last_snippet=last_snippet,
            cross_file_context=cross_file_context or None,
        )
        try:
            content = complete_text(
                client,
                [
                    {"role": "system", "content": FORGE_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                self.config.model,
            )
        except Exception as exc:
            _logger.warning("LLM call failed: %s", exc)
            return ""

        return _extract_code(content)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _task_to_generate_spec(self, task: dict[str, Any]) -> dict[str, Any]:
        """Convert a forge task spec into a generate_code()-compatible spec."""
        atoms = task.get("atoms") or []
        # Normalize inputs -> params for compatibility.
        normalized = []
        for atom in atoms:
            a = dict(atom)
            if "inputs" in a and "params" not in a:
                a["params"] = a.pop("inputs")
            normalized.append(a)

        cross_ctx = self._load_context_files(task)

        if len(normalized) == 1:
            spec = dict(normalized[0])
            spec.setdefault("name", task.get("task_id", "forge_atom"))
            if cross_ctx:
                spec["cross_file_context"] = cross_ctx
        else:
            spec = {
                "module_name": task.get("task_id", "forge_module"),
                "atoms": normalized,
            }
            if cross_ctx:
                spec["cross_file_context"] = cross_ctx

        task_description = task.get("description")
        if task_description:
            spec["task_description"] = task_description
        implementation_notes = task.get("implementation_notes")
        if implementation_notes:
            spec["implementation_notes"] = implementation_notes

        # Propagate target_file so downstream helpers (e.g.
        # _is_std_module in generate_strategy) can detect std/ modules.
        target_file = task.get("target_file")
        if target_file:
            spec["target_file"] = target_file

        return spec

    def _render_deterministic_module(self, task: dict[str, Any]) -> str:
        """Render create/replace module tasks that provide explicit atom bodies."""
        if task.get("deterministic_bodies") is not True:
            return ""
        atoms = task.get("atoms") or []
        if not atoms or any(not isinstance(atom, dict) for atom in atoms):
            return ""
        if any(not (atom.get("body") or atom.get("body_expr")) for atom in atoms):
            return ""

        target_file = str(task.get("target_file", "std/generated.mm"))
        module_name = target_file.removeprefix("std/").removesuffix(".mm")
        alias = module_name.split("/")[-1].replace("-", "_")
        module_title = str(
            task.get("module_title") or f"{target_file} — deterministic forge output"
        )
        lines = [
            "// =============================================================",
            f"// {module_title}",
            "// =============================================================",
            "// 明示 body を持つ forge task から決定的に生成した検証対象。",
            "// LLM 呼び出しなしで forge できる構造的契約のみを含む。",
        ]
        lines.extend(
            [
                "//",
                "// Usage:",
                f'//   import "{module_name}" as {alias};',
                "",
            ]
        )
        for atom in atoms:
            lines.extend(_render_deterministic_atom(atom))
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def _load_context_files(self, task: dict[str, Any]) -> str:
        """Load contents of ``context_files`` specified in the task spec.

        Returns a formatted string with the contents of each file,
        suitable for injection into the LLM prompt.  Returns ``""``
        when no ``context_files`` are declared or none can be read.

        Security: every path is resolved and verified to live inside
        ``self.mumei_repo_dir`` — tasks cannot exfiltrate arbitrary
        host files by supplying a traversal-escaping relative path.
        """
        context_files = task.get("context_files") or []
        if not isinstance(context_files, list) or not context_files:
            return ""

        sections: list[str] = []
        for rel_path in context_files:
            if not isinstance(rel_path, str) or not rel_path:
                continue
            full_path = (self.mumei_repo_dir / rel_path).resolve()
            try:
                full_path.relative_to(self.mumei_repo_dir)
            except ValueError:
                _logger.warning("context_file escapes repo root: %s", rel_path)
                continue
            if not full_path.exists() or not full_path.is_file():
                _logger.warning("context_file not found: %s", rel_path)
                continue
            try:
                content = full_path.read_text(encoding="utf-8")
            except OSError as exc:
                _logger.warning("Failed to read context_file %s: %s", rel_path, exc)
                continue
            sections.append(
                f"# Context file: `{rel_path}`\n"
                f"```mumei\n{content.strip()}\n```"
            )

        if not sections:
            return ""
        return (
            "# Cross-file context — related std modules.\n"
            "# Use these contracts and types as style references.  Do NOT "
            "re-emit them.\n\n"
            + "\n\n".join(sections)
        )

    def _ensure_openai_client(self) -> OpenAI | LLMProvider:
        if self.config is None:
            raise RuntimeError(
                "MumeiForge was constructed without an AgentConfig; "
                "cannot create an OpenAI client. This path is only "
                "reachable outside of --dry-run mode."
            )
        if self._llm_provider is not None:
            return self._llm_provider
        if self._client is None:
            self._client = self.config.create_client()
        return self._client

    def _load_single_task(self, path: Path) -> list[dict[str, Any]]:
        # Resolve bare filenames against the forge_tasks_dir.
        candidate = path if path.is_absolute() else (self.forge_tasks_dir / path)
        if not candidate.exists():
            _logger.error("single-task path not found: %s", candidate)
            return []
        data = json.loads(candidate.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return []
        data.setdefault("mode", "append")
        data.setdefault("priority", 1)
        data.setdefault("max_retries", 5)
        data.setdefault("auto_commit", False)
        data["_spec_path"] = str(candidate)
        return [data]

    def _print_plan(self, tasks: list[dict[str, Any]]) -> None:
        print(f"Forge plan: {len(tasks)} task(s)")
        print(
            f"Harness profile: {self.harness_metrics.profile} "
            f"modules={self.harness_metrics.module_flags}"
        )
        for t in tasks:
            atoms = ", ".join(a.get("name", "?") for a in (t.get("atoms") or []))
            print(
                f"  - [{t.get('priority', 100):>3}] {t.get('task_id', '?')} "
                f"-> {t.get('target_file', '?')} "
                f"(mode={t.get('mode', 'append')}, atoms=[{atoms}])"
            )

    # ------------------------------------------------------------------
    # Git
    # ------------------------------------------------------------------

    def _commit_change(
        self,
        task: dict[str, Any],
        target_rel: str,
        atoms_added: list[str],
    ) -> str | None:
        """Stage + commit the change, returning the resulting commit SHA."""
        task_id = task.get("task_id", "forge-task")
        if not _SAFE_TASK_ID_RE.match(task_id):
            _logger.warning("Refusing to commit — unsafe task_id: %r", task_id)
            return None

        # Ensure a git identity is configured before attempting any commit so
        # that fresh CI runners without a default identity don't blow up.
        _ensure_git_identity(self.mumei_repo_dir)

        add = _git(["add", "--", target_rel], cwd=self.mumei_repo_dir)
        if add.returncode != 0:
            _logger.warning("git add failed: %s", add.stderr.strip())
            return None

        atoms_str = ", ".join(atoms_added) or "new atom(s)"
        message = (
            f"feat(std): forge {atoms_str} ({task_id})\n\n"
            f"Auto-forged by mumei-agent forge mode.\n"
            f"Target file: {target_rel}\n"
        )
        commit = _git(["commit", "-m", message], cwd=self.mumei_repo_dir)
        if commit.returncode != 0:
            _logger.warning("git commit failed: %s", commit.stderr.strip())
            return None

        sha = _git(["rev-parse", "HEAD"], cwd=self.mumei_repo_dir)
        if sha.returncode == 0:
            return sha.stdout.strip()
        return None

    def _record_decidable_fragment_metrics(
        self,
        verify_result: dict[str, Any],
        *,
        first_pass_verified: bool,
    ) -> tuple[list[str], str]:
        generated_at = datetime.datetime.now(datetime.timezone.utc)
        quarter = metrics_quarter(generated_at)
        try:
            metrics = (
                Metrics.from_file(self.metrics_path)
                if self.metrics_path.exists()
                else Metrics()
            )
            tags = metrics.record_verify_result_as_new_spec(
                verify_result,
                first_pass_verified=first_pass_verified,
                generated_at=generated_at,
            )
            self.metrics_path.parent.mkdir(parents=True, exist_ok=True)
            self.metrics_path.write_text(metrics.to_json(), encoding="utf-8")
            return tags, quarter
        except Exception as exc:  # noqa: BLE001
            _logger.debug("Could not record P8-D metrics: %s", exc, exc_info=True)
            return decidable_fragment_tags_from_verify_result(verify_result), quarter

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def log_result(self, task: dict[str, Any], result: ForgeResult) -> None:
        """Append a run entry to the forge log (with advisory file lock)."""
        entry = result.to_dict()
        entry["timestamp"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        entry["task_spec_path"] = task.get("_spec_path")

        self.log_path.parent.mkdir(parents=True, exist_ok=True)

        lock_path = self.log_path.parent / f".{self.log_path.name}.lock"
        with open(lock_path, "w", encoding="utf-8") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                data: dict[str, Any]
                if self.log_path.exists():
                    try:
                        data = json.loads(self.log_path.read_text(encoding="utf-8"))
                        if not isinstance(data, dict) or "runs" not in data:
                            data = {"runs": []}
                    except json.JSONDecodeError:
                        data = {"runs": []}
                else:
                    data = {"runs": []}

                runs = data.setdefault("runs", [])
                runs.append(entry)
                self.log_path.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)


# ---------------------------------------------------------------------------
# Structured-error enrichment
# ---------------------------------------------------------------------------

def _enrich_error_with_report(
    raw_error: str,
    report: dict[str, Any] | None,
) -> str:
    """Augment a raw verifier error log with structured fix hints.

    Re-uses the existing ``report_formatter`` helpers so forge retries
    receive the same counterexample / unsat-core / actionable-fix-hint
    information that the heal and generate strategies already rely on.
    """
    if not report or not isinstance(report, dict):
        return raw_error

    structured_parts: list[str] = []
    try:
        hint = format_actionable_fix_hint(report)
        if hint:
            structured_parts.append(f"Actionable fix hint: {hint}")
    except Exception as exc:  # noqa: BLE001 — formatter must not break retry
        _logger.debug("format_actionable_fix_hint failed: %s", exc)

    try:
        ce = format_counterexample(report)
        if ce:
            structured_parts.append(ce)
    except Exception as exc:  # noqa: BLE001
        _logger.debug("format_counterexample failed: %s", exc)

    try:
        suc = format_structured_unsat_core(report)
        if suc:
            structured_parts.append(f"Structured unsat core:\n{suc}")
    except Exception as exc:  # noqa: BLE001
        _logger.debug("format_structured_unsat_core failed: %s", exc)

    if not structured_parts:
        return raw_error

    return (
        raw_error.rstrip()
        + "\n\n# Structured Analysis:\n"
        + "\n".join(structured_parts)
    )


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------

def build_parser(parser) -> None:  # type: ignore[no-untyped-def]
    """Add forge-specific arguments to *parser*."""
    parser.add_argument(
        "--tasks-dir",
        default="forge_tasks/",
        help="Directory containing forge task spec JSON files (default: forge_tasks/)",
    )
    parser.add_argument(
        "--mumei-repo",
        required=False,
        default=None,
        help="Path to the mumei repo (the one containing std/). "
             "Defaults to the MUMEI_REPO env var or the agent repo root.",
    )
    parser.add_argument(
        "--max-tasks",
        type=int,
        default=None,
        help="Maximum number of tasks to execute (default: all)",
    )
    parser.add_argument(
        "--task",
        default=None,
        help="Run a single task spec file (looked up relative to --tasks-dir "
             "if not absolute)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the execution plan and exit without running anything",
    )
    parser.add_argument(
        "--auto-commit",
        action=argparse_bool_action(),
        default=None,
        help="Override each task's auto_commit flag "
             "(--auto-commit to force on, --no-auto-commit to force off)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=None,
        help="Override each task's max_retries",
    )
    parser.add_argument(
        "--log-path",
        default=None,
        help="Path to forge_log.json (default: <tasks_dir>/../forge_log.json)",
    )
    parser.add_argument(
        "--harness-profile",
        choices=harness_profile_names(),
        default="basic",
        help=(
            "NLAH module-ablation profile. Heavy multi-candidate search is "
            "enabled only by self_evolution/full."
        ),
    )


def argparse_bool_action():
    """Return the BooleanOptionalAction class (lazy import for 3.11+)."""
    import argparse
    return argparse.BooleanOptionalAction


def main(args) -> None:  # type: ignore[no-untyped-def]
    """Entrypoint for ``python -m agent forge``."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    import os

    tasks_dir = Path(args.tasks_dir).resolve()
    mumei_repo = (
        Path(args.mumei_repo).resolve() if args.mumei_repo
        else Path(os.environ.get("MUMEI_REPO", ".")).resolve()
    )

    # --dry-run never reaches the LLM or calls mumei, so we skip the
    # ``AgentConfig()`` construction which raises ``ValueError`` when
    # ``LLM_API_KEY`` / ``OPENAI_API_KEY`` is unset.  The README
    # advertises dry-run as a no-dependency preview, so it must work
    # without an API key configured.
    config: AgentConfig | None = None if args.dry_run else AgentConfig()
    mumei_bin = config.mumei_bin if config else os.environ.get("MUMEI_BIN", "mumei")
    # Use the factory so ``USE_MCP_CLIENT=true`` routes forge verification
    # through the mumei MCP server when available (falls back to the CLI
    # client transparently).
    mumei = create_mumei_client(mumei_bin)

    log_path = Path(args.log_path).resolve() if args.log_path else tasks_dir.parent / "forge_log.json"
    harness_profile = getattr(args, "harness_profile", "basic")
    if not isinstance(harness_profile, str):
        harness_profile = "basic"
    harness_metrics = HarnessMetrics.from_profile(harness_profile)

    forge = MumeiForge(
        config=config,
        mumei_client=mumei,
        mumei_repo_dir=mumei_repo,
        forge_tasks_dir=tasks_dir,
        log_path=log_path,
        harness_metrics=harness_metrics,
    )

    single_task_path = Path(args.task) if args.task else None

    results = forge.run(
        max_tasks=args.max_tasks,
        dry_run=args.dry_run,
        auto_commit_override=args.auto_commit,
        max_retries_override=args.max_retries,
        single_task_path=single_task_path,
    )

    # Summary
    succeeded = [r for r in results if r.status == "success"]
    failed = [r for r in results if r.status == "failed"]
    skipped = [r for r in results if r.status == "skipped"]
    print(
        f"\nForge complete: {len(succeeded)} succeeded, "
        f"{len(failed)} failed, {len(skipped)} skipped."
    )
    for r in results:
        marker = {"success": "+", "failed": "-", "skipped": "."}.get(r.status, "?")
        extra = f" ({r.error})" if r.error else ""
        print(f"  [{marker}] {r.task_id}{extra}")
    print("Harness metrics:")
    print(harness_metrics.aggregate_metrics_json())
