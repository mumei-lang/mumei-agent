"""Blast-radius verification and self-healing helpers for proliferate.

Extracted from :mod:`agent.proliferate` (behaviour-preserving split). These
helpers assess whether a newly forged ``.mm`` file breaks existing ``std/``
files (blast radius) and attempt to repair any broken files via the fix
strategy (self-healing). They are re-exported from :mod:`agent.proliferate`
for backwards compatibility.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from agent.mumei_client import MumeiClient
from agent.thought_log import (
    ThoughtProcess,
    describe_fix,
    summarize_code_diff,
    summarize_z3_result,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Blast radius check
# ---------------------------------------------------------------------------


def check_blast_radius(
    mumei_client: MumeiClient,
    mumei_repo_dir: Path,
    new_file_path: Path,
    code: str,
) -> dict[str, Any]:
    """Check whether adding *code* at *new_file_path* breaks existing std.

    Writes the new ``.mm`` file to *new_file_path*, then verifies every
    existing ``.mm`` file under ``std/``.  On completion the new file is
    removed so the caller decides what to persist.

    Returns::

        {"broken_files": [{"file": ..., "error": ...}], "all_passed": bool}
    """
    std_dir = mumei_repo_dir / "std"
    wrote_new = False
    result: dict[str, Any] = {"broken_files": [], "all_passed": True}

    try:
        # Write new file
        new_file_path.parent.mkdir(parents=True, exist_ok=True)
        new_file_path.write_text(code, encoding="utf-8")
        wrote_new = True

        # Verify every existing .mm file (excluding the new one)
        for mm_file in sorted(std_dir.rglob("*.mm")):
            if mm_file.resolve() == new_file_path.resolve():
                continue
            verify = mumei_client.verify(str(mm_file))
            if not verify["success"]:
                result["broken_files"].append(
                    {"file": str(mm_file), "error": verify.get("stderr", "")}
                )
        result["all_passed"] = len(result["broken_files"]) == 0
    finally:
        # Clean up: remove the new file so caller controls persistence
        if wrote_new and new_file_path.exists():
            try:
                new_file_path.unlink()
            except OSError:
                pass

    return result


# ---------------------------------------------------------------------------
# Self-healing for broken files
# ---------------------------------------------------------------------------


def attempt_heal(
    client: Any,
    model: str,
    broken_info: dict[str, Any],
    mumei_client: MumeiClient,
    max_retries: int = 3,
    thought_process: ThoughtProcess | None = None,
) -> bool:
    """Attempt to heal a broken ``.mm`` file using the fix strategy.

    Uses :func:`agent.strategies.fix_strategy.get_fix` to generate
    candidate fixes, then re-verifies.  Returns ``True`` if the file
    was successfully repaired.
    """
    from agent.strategies.fix_strategy import get_fix

    file_path = broken_info["file"]
    try:
        source_code = Path(file_path).read_text(encoding="utf-8")
    except OSError:
        logger.error("Cannot read broken file %s", file_path)
        return False

    for attempt in range(max_retries):
        verify = mumei_client.verify(file_path)
        if thought_process is not None:
            try:
                thought_process.add_step(
                    action="initial_verify" if attempt == 0 else "re_verify",
                    z3_result=summarize_z3_result(verify),
                    verification_success=bool(verify["success"]),
                    re_verify_success=(
                        bool(verify["success"]) if attempt > 0 else None
                    ),
                )
            except Exception:
                pass
        if verify["success"]:
            if thought_process is not None:
                try:
                    thought_process.final_success = True
                    thought_process.total_attempts = attempt + 1
                except Exception:
                    pass
            return True

        error_log = verify.get("stderr", "") + verify.get("stdout", "")
        report_data = verify.get("report") or {}

        fixed_code = get_fix(
            client=client,
            model=model,
            source_code=source_code,
            error_log=error_log,
            report_data=report_data,
            mumei_client=mumei_client,
            source_path=file_path,
        )
        if thought_process is not None:
            try:
                thought_process.add_step(
                    action="llm_fix",
                    verification_success=False,
                    fix_strategy="llm",
                    fix_description=describe_fix(report_data),
                    code_diff_summary=(
                        summarize_code_diff(source_code, fixed_code)
                        if fixed_code
                        else "No candidate fix produced."
                    ),
                )
            except Exception:
                pass
        if not fixed_code or fixed_code == source_code:
            logger.warning(
                "Heal attempt %d/%d for %s produced no change",
                attempt + 1,
                max_retries,
                file_path,
            )
            continue

        # Write fixed code and re-verify
        Path(file_path).write_text(fixed_code, encoding="utf-8")
        source_code = fixed_code

    # Final check
    final = mumei_client.verify(file_path)
    if thought_process is not None:
        try:
            thought_process.add_step(
                action="re_verify",
                z3_result=summarize_z3_result(final),
                verification_success=bool(final["success"]),
                re_verify_success=bool(final["success"]),
            )
            thought_process.final_success = bool(final["success"])
            thought_process.total_attempts = len(
                [
                    s
                    for s in thought_process.steps
                    if s.action in ("initial_verify", "re_verify")
                ]
            )
        except Exception:
            pass
    return final["success"]
