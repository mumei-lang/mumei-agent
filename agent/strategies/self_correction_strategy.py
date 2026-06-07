"""P9-F self-correction protocol for generate → verify → repair loops."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from openai import OpenAI

from agent.budget_policy import BudgetPolicy, classify_action_class, evaluate_budget
from agent.config import AgentConfig
from agent.metrics import Metrics
from agent.mumei_client import MumeiClient, create_mumei_client
from agent.strategies import fix_strategy
from agent.strategies.generate_strategy import generate_code
from agent.strategies.retry_history import RetryAttempt, RetryHistory


GenerateFn = Callable[[OpenAI, str, dict, int, MumeiClient | None], tuple[str, bool]]


@dataclass
class SelfCorrectionIteration:
    iteration: int
    verification_result: str
    success: bool
    consecutive_successes: int
    repair_attempts: int
    tokens_used: int = 0
    action_class: str = "verify"
    reconstruction_loss_empty: bool = True
    counterexample: dict[str, object] | None = None
    stop_reason: str | None = None


@dataclass
class SelfCorrectionResult:
    converged: bool
    repair_attempts: int
    consecutive_successes: int
    total_tokens: int
    iterations: list[SelfCorrectionIteration] = field(default_factory=list)
    final_error: str | None = None
    stop_reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["self_correction_metadata"] = {
            "repair_attempts": self.repair_attempts,
            "converged": self.converged,
            "final_error": self.final_error,
            "consecutive_successes": self.consecutive_successes,
            "token_cost": self.total_tokens,
        }
        return payload


class SelfCorrectionStrategy:
    """Run a bounded self-correction loop with convergence and token gates."""

    def __init__(
        self,
        client: OpenAI,
        model: str,
        mumei_client: MumeiClient,
        *,
        max_repairs: int = 10,
        required_successes: int = 2,
        max_tokens: int = 10000,
        min_success_rate: float = 0.25,
        budget_policy: BudgetPolicy | None = None,
        metrics: Metrics | None = None,
    ) -> None:
        self.client = client
        self.model = model
        self.mumei_client = mumei_client
        self.max_repairs = max(1, min(max_repairs, 10))
        self.required_successes = max(1, required_successes)
        self.max_tokens = max_tokens
        self.min_success_rate = min_success_rate
        self.budget_policy = budget_policy or BudgetPolicy(
            max_attempts=self.max_repairs,
            max_tokens=max_tokens,
        )
        self.metrics = metrics or Metrics()

    def run(
        self,
        source_path: str | Path,
        *,
        spec: dict | None = None,
        generate_fn: GenerateFn | None = None,
    ) -> SelfCorrectionResult:
        path = Path(source_path)
        if spec is not None and not path.exists():
            generator = generate_fn or self._default_generate
            generated, _verified = generator(
                self.client,
                self.model,
                spec,
                self.max_repairs,
                self.mumei_client,
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(generated, encoding="utf-8")

        history = RetryHistory()
        iterations: list[SelfCorrectionIteration] = []
        consecutive_successes = 0
        total_tokens = 0
        final_error: str | None = None

        for iteration in range(1, self.max_repairs + self.required_successes + 1):
            result = self.mumei_client.verify(str(path))
            report = dict(result.get("report") or {})
            verification_result = self._verification_result(result, report)
            loss_empty = self._reconstruction_loss_empty(report)
            success = verification_result in {"unsat", "lean_verified"} and loss_empty
            consecutive_successes = consecutive_successes + 1 if success else 0

            iterations.append(
                SelfCorrectionIteration(
                    iteration=iteration,
                    verification_result=verification_result,
                    success=success,
                    consecutive_successes=consecutive_successes,
                    repair_attempts=len(history.attempts),
                    reconstruction_loss_empty=loss_empty,
                    counterexample=self._counterexample(report),
                )
            )
            if consecutive_successes >= self.required_successes:
                iterations[-1].stop_reason = "converged"
                return SelfCorrectionResult(
                    converged=True,
                    repair_attempts=len(history.attempts),
                    consecutive_successes=consecutive_successes,
                    total_tokens=total_tokens,
                    iterations=iterations,
                    stop_reason="converged",
                )
            if success:
                continue

            if len(history.attempts) >= self.max_repairs:
                final_error = self._final_error(report, result)
                iterations[-1].stop_reason = "max_repairs_exhausted"
                break
            if total_tokens >= self.max_tokens:
                final_error = self._final_error(report, result)
                iterations[-1].stop_reason = "token_cost_exceeded"
                break
            if self._should_stop_for_low_yield(iterations, total_tokens):
                final_error = self._final_error(report, result)
                iterations[-1].stop_reason = "low_success_rate"
                break

            source = path.read_text(encoding="utf-8")
            logs = str(result.get("stdout") or "") + str(result.get("stderr") or "")
            repeated = history.same_counterexample_signature_seen(report)
            action_class = classify_action_class(report, repeated_signature=repeated)
            decision = evaluate_budget(
                self.budget_policy,
                history,
                report,
                proposed_action_class=action_class,
            )
            if not decision.allowed:
                final_error = decision.reason or self._final_error(report, result)
                iterations[-1].stop_reason = final_error
                break

            fixed = fix_strategy.get_fix(
                self.client,
                self.model,
                source,
                logs,
                report,
                mumei_client=self.mumei_client,
                source_path=str(path),
                retry_history=history,
                metrics=self.metrics,
                budget_policy=self.budget_policy,
                action_class=decision.action_class,
            )
            tokens = int(report.get("llm_tokens_used") or 0)
            total_tokens += tokens
            if not fixed:
                final_error = "no_fix_produced"
                iterations[-1].stop_reason = final_error
                break

            path.write_text(fixed, encoding="utf-8")
            history.add(
                RetryAttempt(
                    attempt_number=len(history.attempts) + 1,
                    source_code=source,
                    error_log=logs,
                    report_data=report,
                    diagnosis={
                        "root_cause": str(report.get("failure_type") or "verification_failed"),
                        "fix_approach": decision.action_class,
                        "target_section": str(report.get("atom") or "unknown"),
                    },
                    action_class=decision.action_class,
                    tokens_used=tokens,
                )
            )
            iterations[-1].tokens_used = tokens
            iterations[-1].action_class = decision.action_class

        return SelfCorrectionResult(
            converged=False,
            repair_attempts=len(history.attempts),
            consecutive_successes=consecutive_successes,
            total_tokens=total_tokens,
            iterations=iterations,
            final_error=final_error,
            stop_reason=iterations[-1].stop_reason if iterations else "not_started",
        )

    @staticmethod
    def _default_generate(
        client: OpenAI,
        model: str,
        spec: dict,
        max_repairs: int,
        mumei_client: MumeiClient | None,
    ) -> tuple[str, bool]:
        return generate_code(
            client,
            model,
            spec,
            config_max_retries=max_repairs,
            mumei_client=mumei_client,
        )

    @staticmethod
    def _verification_result(result: dict, report: dict) -> str:
        if result.get("success"):
            raw = report.get("z3_check_result") or report.get("z3_result_class")
            if raw in {"lean_verified", "unsat"}:
                return str(raw)
            atoms = report.get("atoms")
            if isinstance(atoms, list) and atoms:
                atom_results = {
                    str(atom.get("z3_check_result") or atom.get("status"))
                    for atom in atoms
                    if isinstance(atom, dict)
                }
                if atom_results and atom_results <= {"unsat", "lean_verified", "verified"}:
                    return "lean_verified" if "lean_verified" in atom_results else "unsat"
            return "unsat"
        return str(
            report.get("z3_check_result")
            or report.get("z3_result_class")
            or report.get("failure_type")
            or report.get("status")
            or "failed"
        )

    @staticmethod
    def _reconstruction_loss_empty(report: dict) -> bool:
        loss = (
            report.get("reconstruction_loss")
            or _dict_get(report.get("semantic_feedback"), "reconstruction_loss")
            or _dict_get(report.get("structured_feedback"), "reconstruction_loss")
        )
        if loss is None:
            return True
        if isinstance(loss, list):
            return len(loss) == 0
        if isinstance(loss, dict):
            is_zero = loss.get("is_zero_loss")
            if isinstance(is_zero, bool):
                return is_zero
            size = loss.get("loss_set_size")
            if isinstance(size, int):
                return size == 0
            vector = loss.get("loss_vector")
            if vector is None:
                return not bool(loss.get("counter_example") or loss.get("counterexample"))
            if isinstance(vector, list):
                if all(isinstance(item, int | float) for item in vector):
                    return all(_numeric_zero(item) for item in vector)
                return len(vector) == 0
        return False

    @staticmethod
    def _counterexample(report: dict) -> dict[str, object] | None:
        value = (
            report.get("counterexample")
            or _dict_get(report.get("reconstruction_loss"), "counter_example")
            or _dict_get(report.get("semantic_feedback"), "counterexample")
        )
        return value if isinstance(value, dict) else None

    @staticmethod
    def _final_error(report: dict, result: dict) -> str:
        return str(
            report.get("failure_type")
            or report.get("reason")
            or result.get("stderr")
            or "verification_failed"
        )

    def _should_stop_for_low_yield(
        self,
        iterations: list[SelfCorrectionIteration],
        total_tokens: int,
    ) -> bool:
        if len(iterations) < 4 or total_tokens < self.max_tokens // 2:
            return False
        success_rate = sum(1 for item in iterations if item.success) / len(iterations)
        repeated_failures = self._inefficient_repair_pattern(iterations)
        return success_rate < self.min_success_rate or repeated_failures

    @staticmethod
    def _inefficient_repair_pattern(iterations: list[SelfCorrectionIteration]) -> bool:
        failures = [item for item in iterations if not item.success and item.counterexample]
        if len(failures) < 2:
            return False
        return failures[-1].counterexample == failures[-2].counterexample


def _dict_get(value: object, key: str) -> object | None:
    if isinstance(value, dict):
        return value.get(key)
    return None


def _numeric_zero(value: object) -> bool:
    try:
        return abs(float(value)) <= 1e-9
    except (TypeError, ValueError):
        return False


def build_parser(parser: argparse.ArgumentParser | None = None) -> argparse.ArgumentParser:
    parser = parser or argparse.ArgumentParser(
        description="Run P9-F self-correction until convergence."
    )
    parser.add_argument("source_file", help="Mumei .mm source to repair")
    parser.add_argument("--spec-file", help="Optional JSON spec to generate initial source")
    parser.add_argument("--metadata-output", help="Write self-correction metadata JSON")
    parser.add_argument("--max-repairs", type=int, default=10)
    parser.add_argument("--required-successes", type=int, default=None)
    parser.add_argument("--max-tokens", type=int, default=10000)
    return parser


def main(args: argparse.Namespace | None = None) -> SelfCorrectionResult:
    if args is None:
        args = build_parser().parse_args()
    config = AgentConfig()
    required_successes = (
        args.required_successes
        if args.required_successes is not None
        else config.self_correction_convergence_threshold
    )
    strategy = SelfCorrectionStrategy(
        config.create_client(),
        config.model,
        create_mumei_client(config.mumei_bin),
        max_repairs=args.max_repairs or config.self_correction_max_attempts,
        required_successes=required_successes,
        max_tokens=args.max_tokens,
    )
    spec = None
    if args.spec_file:
        spec = json.loads(Path(args.spec_file).read_text(encoding="utf-8"))
    result = strategy.run(args.source_file, spec=spec)
    payload = result.to_dict()
    if args.metadata_output:
        Path(args.metadata_output).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return result
