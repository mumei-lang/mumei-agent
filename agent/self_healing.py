"""Mumei Self-Healing Loop: AI-driven autonomous fix loop.

Reads source code, runs mumei verify --json, and
uses LLM to fix verification failures iteratively.
"""
import argparse
import json
import shutil
import sys
import time
import datetime
import fcntl
from pathlib import Path

from agent.budget_policy import (
    BudgetPolicy,
    classify_action_class,
    compute_policy_fingerprint,
    evaluate_budget,
    load_budget_policy,
)
from agent.budget_metrics import aggregate_metrics
from agent.config import AgentConfig
from agent.metrics import Metrics
from agent.mumei_client import create_mumei_client
from agent.pattern_library import PatternLibrary
from agent.strategies.fix_strategy import get_fix
from agent.strategies.generate_strategy import generate_code
from agent.strategies.retry_history import RetryAttempt, RetryHistory
from agent.thought_log import (
    ThoughtProcess,
    describe_fix,
    infer_fix_strategy,
    summarize_code_diff,
    summarize_z3_result,
)

ROOT_DIR = Path(__file__).parent.parent.absolute()
HISTORY_FILE = ROOT_DIR / "visualizer" / "report_history.json"


def sync_to_visualizer(report_data: dict, *, enabled: bool = True) -> None:
    """Write report data to visualizer/ and append to history.

    Args:
        report_data: The report dict (from mumei verify --json).
        enabled: Whether visualizer sync is enabled.
    """
    if not enabled:
        return
    if not report_data:
        return

    vis_dir = ROOT_DIR / "visualizer"
    vis_dir.mkdir(exist_ok=True)
    (vis_dir / "report.json").write_text(
        json.dumps(report_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Append to history (with file lock to prevent corruption)
    entry = dict(report_data)
    entry["timestamp"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    lock_file = HISTORY_FILE.parent / ".report_history.lock"
    lock_file.parent.mkdir(exist_ok=True)
    with open(lock_file, "w", encoding="utf-8") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            history = []
            if HISTORY_FILE.exists():
                try:
                    history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    history = []
            history.append(entry)
            HISTORY_FILE.write_text(
                json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def main() -> None:
    """Run the self-healing loop."""
    parser = argparse.ArgumentParser(
        description="Mumei Self-Healing Loop: AI-driven autonomous fix loop"
    )
    parser.add_argument(
        "source_file",
        nargs="?",
        default="examples/sword_test.mm",
        help="Path to the .mm source file to heal (default: examples/sword_test.mm)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=None,
        help="Maximum number of fix attempts (default: from config or 5)",
    )
    parser.add_argument(
        "--strategy",
        choices=["single", "multi-stage"],
        default=None,
        help="Fix strategy: 'single' (one-shot) or 'multi-stage' (diagnose→fix→validate). "
             "Default: from AGENT_STRATEGY env var or 'single'.",
    )
    parser.add_argument(
        "--generate",
        type=str,
        default=None,
        metavar="SPEC_JSON",
        help="Generate mode: path to a JSON spec file describing the atom to generate. "
             "Runs generate → verify → fix loop instead of the normal heal loop.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        metavar="OUTPUT_FILE",
        help="Output file for generated code (required with --generate).",
    )
    parser.add_argument(
        "--budget-policy",
        type=str,
        default=None,
        metavar="POLICY_JSON",
        help="Path to retry budget policy JSON (default: built-in P8-G policy).",
    )
    args = parser.parse_args()

    if args.generate is not None and args.output is None:
        parser.error("--output is required when using --generate")

    source_file = args.source_file
    config = AgentConfig()
    if args.strategy is not None:
        config.strategy = args.strategy
    client = config.create_client()
    # Use the factory so ``USE_MCP_CLIENT=true`` transparently routes
    # verification through the mumei MCP server when it's reachable,
    # while keeping the subprocess CLI as the default/fallback.
    mumei = create_mumei_client(config.mumei_bin)

    max_retries = args.max_retries if args.max_retries is not None else config.max_retries
    budget_policy = load_budget_policy(args.budget_policy)
    max_retries = min(max_retries, budget_policy.max_attempts)

    # --- Generate mode (P1-A): generate → verify → fix loop ---
    if args.generate is not None:
        success = True
        _run_generate_mode(
            client, config.model, args.generate,
            output_file=args.output,
            max_retries=max_retries,
            mumei_client=mumei,
        )
        return

    print("Mumei Self-Healing Loop Start...")

    # Back up original source before any modifications
    backup_file = source_file + ".bak"
    shutil.copy2(source_file, backup_file)
    print(f"Original source backed up to {backup_file}")

    success = False
    outer_history = RetryHistory()
    pattern_lib = PatternLibrary()
    thought = ThoughtProcess(target_file=source_file)
    try:
        for attempt in range(max_retries + 1):
            result = mumei.verify(source_file)
            report = result["report"] or {}
            try:
                thought.add_step(
                    action="initial_verify" if attempt == 0 else "re_verify",
                    z3_result=summarize_z3_result(result),
                    verification_success=bool(result["success"]),
                    re_verify_success=(
                        bool(result["success"]) if attempt > 0 else None
                    ),
                )
            except Exception:
                pass

            if result["success"]:
                print(f"Success! Blade is flawless (Attempt {attempt + 1}).")
                try:
                    sync_to_visualizer(report, enabled=config.visualizer_sync)
                except Exception:
                    pass
                # Record the successful fix in the pattern library so that
                # single-shot LLM fixes (which are not validated inside
                # get_fix) are captured for future few-shot examples.
                if attempt > 0 and outer_history.attempts:
                    last = outer_history.attempts[-1]
                    try:
                        with open(source_file, "r", encoding="utf-8") as f:
                            fixed_source = f.read()
                        vt = (last.report_data.get("violation_type")
                              or last.report_data.get("failure_type", "unknown"))
                        pattern_lib.record(
                            violation_type=vt,
                            failure_type=last.report_data.get("failure_type", ""),
                            source_before=last.source_code,
                            source_after=fixed_source,
                            report=last.report_data,
                            fix_method="llm",
                        )
                    except Exception:
                        pass
                success = True
                metrics = aggregate_metrics(outer_history)
                print(
                    "Retry budget metrics: "
                    f"attempts={metrics.attempts_to_success}, "
                    f"tokens={metrics.tokens_to_success}, "
                    f"solver_seconds={metrics.solver_seconds_to_success:.3f}, "
                    f"spec_drift={metrics.spec_drift_score:.3f}, "
                    f"policy_fingerprint={compute_policy_fingerprint(budget_policy)}"
                )
                try:
                    thought.final_success = True
                    thought.total_attempts = attempt + 1
                except Exception:
                    pass
                return

            print(f"Attempt {attempt + 1}: Flaw detected. Consulting AI...")
            logs = result["stdout"] + result["stderr"]

            if not report:
                print("Warning: report.json not found. Using stub report.")
                report = {"status": "error", "reason": "Report not found"}

            # Visualizer sync
            try:
                sync_to_visualizer(report, enabled=config.visualizer_sync)
            except Exception:
                pass

            # On the last iteration, don't generate a fix — all retries exhausted
            if attempt >= max_retries:
                summary = evaluate_budget(
                    BudgetPolicy(max_attempts=len(outer_history.attempts)),
                    outer_history,
                    report,
                    proposed_action_class=classify_action_class(report),
                ).summary
                summary["reason"] = "max_retries_exhausted"
                print(json.dumps(summary, indent=2, ensure_ascii=False))
                break

            with open(source_file, "r", encoding="utf-8") as f:
                source = f.read()
            action_class = classify_action_class(
                report,
                repeated_signature=outer_history.same_counterexample_signature_seen(report),
            )
            decision = evaluate_budget(
                budget_policy,
                outer_history,
                report,
                proposed_action_class=action_class,
            )
            if not decision.allowed:
                print(json.dumps(decision.summary, indent=2, ensure_ascii=False))
                return

            # Get fix from AI
            fixed_code = get_fix(
                client, config.model, source, logs, report,
                strategy=config.strategy,
                mumei_client=mumei,
                source_path=source_file,
                retry_history=outer_history,
                pattern_library=pattern_lib,
                budget_policy=budget_policy,
                action_class=decision.action_class,
            )
            # Record this accepted attempt after fix selection so nested
            # budget checks only see completed prior attempts.
            outer_history.add(
                RetryAttempt(
                    attempt_number=len(outer_history.attempts) + 1,
                    source_code=source,
                    error_log=logs,
                    report_data=report,
                    diagnosis={},  # outer loop has no standalone diagnosis
                    action_class=decision.action_class,
                    tokens_used=int(report.get("llm_tokens_used") or 0),
                    solver_time_seconds=_solver_seconds_from_report(report),
                    spec_drift_score=_spec_drift_from_report(report),
                )
            )
            try:
                thought.add_step(
                    action="llm_fix",
                    verification_success=False,
                    fix_strategy=infer_fix_strategy(report),
                    fix_description=describe_fix(report),
                    code_diff_summary=(
                        summarize_code_diff(source, fixed_code)
                        if fixed_code
                        else "No candidate fix produced."
                    ),
                )
            except Exception:
                pass

            # Validate before overwriting
            if not fixed_code:
                if "manual_review_required" in report:
                    print(json.dumps(report["manual_review_required"], indent=2, ensure_ascii=False))
                    return
                print("Warning: AI returned empty fix. Skipping overwrite.")
                continue

            # Overwrite source file
            with open(source_file, "w", encoding="utf-8") as f:
                f.write(fixed_code)

            print("Code updated. Retrying...")
            time.sleep(2)

    except Exception as exc:
        print(f"Error during healing: {exc}")
    finally:
        try:
            thought.final_success = success
            thought.total_attempts = len(
                [s for s in thought.steps if s.action in ("initial_verify", "re_verify")]
            )
            thought_path = ROOT_DIR / "visualizer" / "thought_process.json"
            thought_path.parent.mkdir(exist_ok=True)
            thought_path.write_text(
                json.dumps(thought.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            print(
                "Thought process: "
                + json.dumps(thought.to_dict(), ensure_ascii=False)
            )
        except Exception:
            pass
        # Restore original source on failure so the user isn't left with
        # broken code. This runs on retries exhausted, exceptions, and any
        # other non-success exit. On success, `return` executes the finally
        # block but the guard skips restoration.
        if not success:
            shutil.copy2(backup_file, source_file)
            print(f"Healing failed. Original source restored from {backup_file}")
            sys.exit(1)


def _solver_seconds_from_report(report: dict) -> float:
    raw = (
        report.get("solver_seconds")
        or report.get("solver_time_seconds")
        or report.get("z3_check_time_seconds")
        or 0.0
    )
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _spec_drift_from_report(report: dict) -> float:
    raw = (
        report.get("spec_drift_score")
        or report.get("semantic_delta")
        or report.get("intent_drift_score")
        or 0.0
    )
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _run_generate_mode(
    client,
    model: str,
    spec_path: str,
    output_file: str,
    max_retries: int,
    mumei_client,
) -> None:
    """Run the generate → verify → fix loop.

    Reads a JSON specification file (single-atom or multi-atom),
    generates Mumei code from it, then verifies and iteratively
    fixes the generated code.  Multi-atom specs are handled
    transparently by ``generate_code()``'s internal dispatch.
    """
    print("Mumei Generate Mode Start...")

    spec_data = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    metrics = Metrics()

    code, verified = generate_code(
        client,
        model,
        spec_data,
        config_max_retries=max_retries,
        mumei_client=mumei_client,
        metrics=metrics,
    )

    if not code:
        print("Error: Generation produced no code.")
        sys.exit(1)

    Path(output_file).write_text(code, encoding="utf-8")

    if verified:
        print(f"Success! Generated and verified code written to {output_file}")
        print(f"Metrics: {metrics.to_json()}")
    else:
        print(f"Warning: Generated code written to {output_file} but verification failed.")
        print(f"Metrics: {metrics.to_json()}")
        sys.exit(1)


if __name__ == "__main__":
    main()
