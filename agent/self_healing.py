"""Mumei Self-Healing Loop: AI-driven autonomous fix loop.

Reads source code, runs mumei build (which triggers verification), and
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

from agent.config import AgentConfig
from agent.mumei_client import MumeiClient
from agent.strategies.fix_strategy import get_fix

REPORT_FILE = "report.json"
ROOT_DIR = Path(__file__).parent.parent.absolute()
HISTORY_FILE = ROOT_DIR / "visualizer" / "report_history.json"


def sync_to_visualizer(report_path: str, *, enabled: bool = True) -> None:
    """Copy report.json to visualizer/ and append to history.

    Args:
        report_path: Path to the report.json file.
        enabled: Whether visualizer sync is enabled.
    """
    if not enabled:
        return
    report_file = Path(report_path)
    if not report_file.exists():
        return

    vis_dir = ROOT_DIR / "visualizer"
    vis_dir.mkdir(exist_ok=True)
    shutil.copy(report_file, vis_dir / "report.json")

    # Append to history (with file lock to prevent corruption)
    entry = json.loads(report_file.read_text(encoding="utf-8"))
    entry["timestamp"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    lock_file = HISTORY_FILE.parent / ".report_history.lock"
    lock_file.parent.mkdir(exist_ok=True)
    with open(lock_file, "w") as lf:
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
    args = parser.parse_args()

    config = AgentConfig()
    client = config.create_client()
    mumei = MumeiClient(config.mumei_bin)

    source_file = args.source_file
    max_retries = args.max_retries if args.max_retries is not None else config.max_retries

    print("Mumei Self-Healing Loop Start...")

    # Back up original source before any modifications
    backup_file = source_file + ".bak"
    shutil.copy2(source_file, backup_file)
    print(f"Original source backed up to {backup_file}")

    # Candidate paths where mumei may write report.json.
    # Note: we check existence but not freshness — if mumei build does not
    # overwrite report.json on success, a stale failure report may be read.
    # This is acceptable because mumei build is expected to always produce
    # report.json; if that assumption changes, add mtime or content checks.
    report_candidates = [
        Path(REPORT_FILE),
        Path(source_file).parent / REPORT_FILE,
    ]

    success = False
    try:
        for attempt in range(max_retries + 1):
            result = mumei.build(source_file)

            # Find the report file (shared by success and failure paths)
            found_report_path = None
            for candidate in report_candidates:
                if candidate.exists():
                    found_report_path = str(candidate)
                    break

            if result["success"]:
                print(f"Success! Blade is flawless (Attempt {attempt + 1}).")
                try:
                    if found_report_path:
                        sync_to_visualizer(found_report_path, enabled=config.visualizer_sync)
                except Exception:
                    pass
                success = True
                return

            print(f"Attempt {attempt + 1}: Flaw detected. Consulting AI...")
            logs = result["stdout"] + result["stderr"]

            # Read the latest verification report
            report = None
            if found_report_path:
                try:
                    report = json.loads(Path(found_report_path).read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    pass
            if report is None:
                print("Warning: report.json not found. Using stub report.")
                report = {"status": "error", "reason": "Report not found"}

            # Visualizer sync
            try:
                if found_report_path:
                    sync_to_visualizer(found_report_path, enabled=config.visualizer_sync)
            except Exception:
                pass

            # On the last iteration, don't generate a fix — all retries exhausted
            if attempt >= max_retries:
                break

            with open(source_file, "r", encoding="utf-8") as f:
                source = f.read()

            # Get fix from AI
            fixed_code = get_fix(client, config.model, source, logs, report)

            # Validate before overwriting
            if not fixed_code:
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
        # Restore original source on failure so the user isn't left with
        # broken code.  This runs on retries exhausted, exceptions (including
        # KeyboardInterrupt via the finally block), and any other non-success
        # exit.  On success, `return` executes the finally block but the
        # guard skips restoration.
        if not success:
            shutil.copy2(backup_file, source_file)
            print(f"Healing failed. Original source restored from {backup_file}")
            sys.exit(1)


if __name__ == "__main__":
    main()
