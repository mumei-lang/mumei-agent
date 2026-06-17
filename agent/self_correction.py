"""P9-F structured-feedback self-correction loop."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from openai import OpenAI

from agent.config import AgentConfig
from agent.mumei_client import MumeiClient, create_mumei_client
from agent.strategies import fix_strategy

MAX_REPAIR_ATTEMPTS = 10

RepairFn = Callable[
    [OpenAI, str, str, dict[str, object], dict[str, object], MumeiClient, Path],
    str | None,
]


@dataclass
class SelfCorrectionLoopIteration:
    iteration: int
    verification_result: str
    success: bool
    consecutive_successes: int
    repair_attempts: int
    token_cost: int
    structured_feedback: dict[str, object] = field(default_factory=dict)
    stop_reason: str | None = None


@dataclass
class SelfCorrectionLoopResult:
    converged: bool
    repair_attempts: int
    consecutive_successes: int
    token_cost: int
    iterations: list[SelfCorrectionLoopIteration] = field(default_factory=list)
    stop_reason: str | None = None
    final_error: str | None = None

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["self_correction_metadata"] = {
            "converged": self.converged,
            "repair_attempts": self.repair_attempts,
            "consecutive_successes": self.consecutive_successes,
            "token_cost": self.token_cost,
            "stop_reason": self.stop_reason,
            "convergence_condition_met": self.converged or self.stop_reason == "max_retries_reached",
        }
        return payload


class StructuredFeedbackSelfCorrectionLoop:
    """Repair a source file using P9-E structured feedback until P9-F convergence."""

    def __init__(
        self,
        client: OpenAI,
        model: str,
        mumei_client: MumeiClient,
        *,
        max_retries: int = MAX_REPAIR_ATTEMPTS,
        convergence_threshold: int = 2,
        max_tokens: int = 10000,
        repair_fn: RepairFn | None = None,
    ) -> None:
        self.client = client
        self.model = model
        self.mumei_client = mumei_client
        self.max_retries = max(1, min(max_retries, MAX_REPAIR_ATTEMPTS))
        self.convergence_threshold = max(1, convergence_threshold)
        self.max_tokens = max(1, max_tokens)
        self.repair_fn = repair_fn or default_repair

    def run(
        self,
        source_path: str | Path,
        structured_feedback: dict[str, object] | str | Path,
    ) -> SelfCorrectionLoopResult:
        path = Path(source_path)
        current_feedback = load_structured_feedback(structured_feedback)
        iterations: list[SelfCorrectionLoopIteration] = []
        consecutive_successes = 0
        repair_attempts = 0
        token_cost = 0
        final_error: str | None = None

        for iteration in range(1, self.max_retries + self.convergence_threshold + 1):
            if token_cost >= self.max_tokens:
                return _finish(
                    False,
                    repair_attempts,
                    consecutive_successes,
                    token_cost,
                    iterations,
                    "token_cost_exceeded",
                    final_error,
                )
            if repair_attempts >= MAX_REPAIR_ATTEMPTS:
                return _finish(
                    False,
                    repair_attempts,
                    consecutive_successes,
                    token_cost,
                    iterations,
                    "hard_repair_limit_reached",
                    final_error,
                )

            result = self.mumei_client.verify(str(path))
            report = _report_dict(result.get("report"))
            current_feedback = _structured_feedback(report) or current_feedback
            success = bool(result.get("success")) and _reconstruction_loss_empty(report, current_feedback)
            consecutive_successes = consecutive_successes + 1 if success else 0
            verification_result = _verification_result(result, report)

            iterations.append(
                SelfCorrectionLoopIteration(
                    iteration=iteration,
                    verification_result=verification_result,
                    success=success,
                    consecutive_successes=consecutive_successes,
                    repair_attempts=repair_attempts,
                    token_cost=token_cost,
                    structured_feedback=current_feedback,
                )
            )

            if consecutive_successes >= self.convergence_threshold:
                iterations[-1].stop_reason = "converged"
                return _finish(
                    True,
                    repair_attempts,
                    consecutive_successes,
                    token_cost,
                    iterations,
                    "converged",
                    None,
                )

            if success:
                continue

            final_error = _final_error(report, result)
            if repair_attempts >= self.max_retries:
                iterations[-1].stop_reason = "max_retries_reached"
                return _finish(
                    False,
                    repair_attempts,
                    consecutive_successes,
                    token_cost,
                    iterations,
                    "max_retries_reached",
                    final_error,
                )

            repair_report = dict(report)
            repair_report["structured_feedback"] = current_feedback
            source = path.read_text(encoding="utf-8")
            fixed = self.repair_fn(
                self.client,
                self.model,
                source,
                current_feedback,
                repair_report,
                self.mumei_client,
                path,
            )
            token_cost += _token_cost(repair_report, current_feedback)
            if token_cost >= self.max_tokens:
                iterations[-1].stop_reason = "token_cost_exceeded"
                return _finish(
                    False,
                    repair_attempts,
                    consecutive_successes,
                    token_cost,
                    iterations,
                    "token_cost_exceeded",
                    final_error,
                )
            if not fixed:
                iterations[-1].stop_reason = "no_fix_produced"
                return _finish(
                    False,
                    repair_attempts,
                    consecutive_successes,
                    token_cost,
                    iterations,
                    "no_fix_produced",
                    final_error,
                )
            path.write_text(fixed, encoding="utf-8")
            repair_attempts += 1
            iterations[-1].repair_attempts = repair_attempts
            iterations[-1].token_cost = token_cost

        return _finish(
            False,
            repair_attempts,
            consecutive_successes,
            token_cost,
            iterations,
            "max_retries_reached",
            final_error,
        )


def default_repair(
    client: OpenAI,
    model: str,
    source: str,
    structured_feedback: dict[str, object],
    report: dict[str, object],
    mumei_client: MumeiClient,
    source_path: Path,
) -> str | None:
    feedback_json = json.dumps(structured_feedback, indent=2, ensure_ascii=False)
    logs = f"structured_feedback:\n{feedback_json}"
    return fix_strategy.get_fix(
        client,
        model,
        source,
        logs,
        report,
        mumei_client=mumei_client,
        source_path=str(source_path),
    )


def run_self_correction_loop(
    source_path: str | Path,
    structured_feedback: dict[str, object] | str | Path,
    *,
    config: AgentConfig | None = None,
    client: OpenAI | None = None,
    mumei_client: MumeiClient | None = None,
    repair_fn: RepairFn | None = None,
) -> SelfCorrectionLoopResult:
    effective_config = config or AgentConfig()
    loop = StructuredFeedbackSelfCorrectionLoop(
        client or effective_config.create_client(),
        effective_config.model,
        mumei_client or create_mumei_client(effective_config.mumei_bin),
        max_retries=effective_config.self_correction_max_attempts,
        convergence_threshold=effective_config.self_correction_convergence_threshold,
        max_tokens=effective_config.self_correction_max_tokens,
        repair_fn=repair_fn,
    )
    return loop.run(source_path, structured_feedback)


def build_self_correct_parser(
    parser: argparse.ArgumentParser | None = None,
) -> argparse.ArgumentParser:
    parser = parser or argparse.ArgumentParser(
        description="Run the P9-F structured-feedback self-correction loop."
    )
    parser.add_argument("source_file", nargs="?", help="Mumei .mm source to repair")
    parser.add_argument("--source", help="Mumei .mm source to repair")
    parser.add_argument(
        "--feedback",
        help="Path to structured feedback JSON, or an inline JSON object.",
    )
    parser.add_argument("--max-iterations", type=int, default=None)
    parser.add_argument("--metadata-output", help="Write self-correction metadata JSON")
    return parser


def main_self_correct(
    args: argparse.Namespace | None = None,
) -> SelfCorrectionLoopResult | fix_strategy.SelfCorrectionResult:
    if args is None:
        args = build_self_correct_parser().parse_args()
    source = args.source or args.source_file
    if not source:
        raise SystemExit("--source or source_file is required")
    config = AgentConfig()
    if args.feedback:
        result = run_self_correction_loop(
            source_path=source,
            structured_feedback=args.feedback,
            config=config,
        )
        payload = result.to_dict()
    else:
        mumei_client = create_mumei_client(config.mumei_bin)
        loop = fix_strategy.SelfCorrectionLoop(
            max_iterations=args.max_iterations or config.self_correction_max_attempts,
            convergence_threshold=float(config.self_correction_convergence_threshold),
        )
        llm_client = fix_strategy.ConfiguredLossVectorFixClient(config, mumei_client)
        result = loop.run(Path(source), mumei_client, llm_client)
        payload = result.to_dict()
    if args.metadata_output:
        Path(args.metadata_output).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return result


def load_structured_feedback(value: dict[str, object] | str | Path) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    raw = str(value)
    if raw.lstrip().startswith("{"):
        payload = json.loads(raw)
    else:
        text_or_path = Path(raw)
        if text_or_path.exists():
            payload = json.loads(text_or_path.read_text(encoding="utf-8"))
        else:
            payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("structured_feedback JSON must be an object")
    return payload


def _finish(
    converged: bool,
    repair_attempts: int,
    consecutive_successes: int,
    token_cost: int,
    iterations: list[SelfCorrectionLoopIteration],
    stop_reason: str,
    final_error: str | None,
) -> SelfCorrectionLoopResult:
    return SelfCorrectionLoopResult(
        converged=converged,
        repair_attempts=repair_attempts,
        consecutive_successes=consecutive_successes,
        token_cost=token_cost,
        iterations=iterations,
        stop_reason=stop_reason,
        final_error=final_error,
    )


def _report_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _structured_feedback(report: dict[str, object]) -> dict[str, object]:
    feedback = report.get("structured_feedback")
    if isinstance(feedback, dict):
        return feedback
    return {}


def _reconstruction_loss_empty(
    report: dict[str, object],
    structured_feedback: dict[str, object],
) -> bool:
    loss = (
        report.get("reconstruction_loss")
        or _dict_get(report.get("semantic_feedback"), "reconstruction_loss")
        or structured_feedback.get("reconstruction_loss")
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
        counterexample = loss.get("counter_example") or loss.get("counterexample")
        if isinstance(counterexample, dict):
            return len(counterexample) == 0
        vector = loss.get("loss_vector")
        if isinstance(vector, list):
            return len(vector) == 0
    return False


def _dict_get(value: object, key: str) -> object | None:
    if isinstance(value, dict):
        return value.get(key)
    return None


def _verification_result(result: dict[str, object], report: dict[str, object]) -> str:
    if result.get("success"):
        return "unsat"
    return str(
        report.get("z3_check_result")
        or report.get("z3_result_class")
        or report.get("failure_type")
        or report.get("status")
        or "verification_failed"
    )


def _final_error(report: dict[str, object], result: dict[str, object]) -> str:
    return str(
        report.get("failure_type")
        or report.get("error_type")
        or result.get("stderr")
        or "verification_failed"
    )


def _token_cost(report: dict[str, object], structured_feedback: dict[str, object]) -> int:
    value = report.get("llm_tokens_used") or structured_feedback.get("token_cost") or 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0
