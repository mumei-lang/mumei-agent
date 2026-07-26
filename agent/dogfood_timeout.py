"""Per-file timeout supervision for dogfood corpus audits.

Large functions, inline assembly, and deeply nested generics are the three
shapes that historically pushed a single corpus file past the whole job's CI
budget.  This module audits one file in a child process so an individual file
can be abandoned without losing the rest of the corpus, and it records why the
file was expensive so triage does not have to re-run it.

A timed-out file stays inside the existing verdict vocabulary: it is reported
as ``unverifiable`` with a ``timed out`` error, which
``agent.dogfood_triage`` folds into the existing ``timeout`` subcategory.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import multiprocessing
from pathlib import Path
import re
import time

from agent.audit import AuditPipeline, _finalize_audit_result
from agent.audit_models import AuditResult
from agent.config import AgentConfig

#: A function body longer than this many lines is reported as a large function.
LARGE_FUNCTION_LINES = 120

_FUNCTION_START = re.compile(
    r"^\s*(?:pub\s+|export\s+|async\s+|static\s+|final\s+|private\s+|public\s+|internal\s+|external\s+)*"
    r"(?:func|fn|def|function|contract|library|impl|class)\b"
)
_INLINE_ASSEMBLY = re.compile(
    r"\bassembly\s*(?:\(\s*\"[^\"]*\"\s*\))?\s*\{"  # solidity
    r"|\basm!\s*\(|\bllvm_asm!\s*\(|\bglobal_asm!\s*\("  # rust
    r"|\b__asm__\b|\basm\s+volatile\b"  # c/c++
)
_GENERIC_PARAMS = re.compile(r"[A-Za-z_][\w.]*<[^<>]*<")
_WHERE_CLAUSE = re.compile(r"^\s*where\b")


@dataclass
class FileAuditTiming:
    """Wall-clock cost and structural risk markers for one audited file."""

    source_file: str
    elapsed_s: float
    timed_out: bool = False
    risk_markers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation of the timing record."""
        return asdict(self)


def source_risk_markers(path: Path) -> list[str]:
    """Return the structural reasons ``path`` may be slow to audit.

    The markers are advisory only; they never change a file's verdict.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = text.splitlines()

    markers: list[str] = []
    starts = [i for i, line in enumerate(lines) if _FUNCTION_START.search(line)]
    boundaries = [*starts[1:], len(lines)]
    if any(
        end - start > LARGE_FUNCTION_LINES
        for start, end in zip(starts, boundaries)
    ):
        markers.append("large_function")
    if _INLINE_ASSEMBLY.search(text):
        markers.append("inline_assembly")
    if _GENERIC_PARAMS.search(text) or sum(
        1 for line in lines if _WHERE_CLAUSE.search(line)
    ) >= 3:
        markers.append("complex_generics")
    return markers


def _timeout_result(
    path: Path, language: str, timeout_s: float, markers: list[str]
) -> AuditResult:
    detail = f" (risk markers: {', '.join(markers)})" if markers else ""
    result = AuditResult(
        success=False,
        source_file=str(path),
        language=language,
        spec_extracted=False,
        verification_status="unverifiable",
        errors=[f"audit timed out after {timeout_s:g}s{detail}"],
    )
    return _finalize_audit_result(result)


def _audit_worker(
    source_file: str,
    language: str,
    queue: "multiprocessing.Queue[object]",
) -> None:
    """Audit one file in a child process and ship the result back."""
    try:
        pipeline = AuditPipeline(config=AgentConfig())
        queue.put(pipeline.audit_file(source_file, language or None))
    except Exception as exc:  # pragma: no cover - defensive, mirrors audit_directory
        queue.put(RuntimeError(f"audit failed: {exc}"))


def audit_file_with_timeout(
    path: Path,
    language: str,
    timeout_s: float,
) -> tuple[AuditResult, FileAuditTiming]:
    """Audit ``path``, abandoning it if it outlives ``timeout_s`` seconds.

    The audit runs in a spawned child process so an unbounded solver or parser
    loop can actually be killed; ``timeout_s <= 0`` audits in-process without
    supervision.
    """
    markers = source_risk_markers(path)
    started = time.monotonic()

    if timeout_s <= 0:
        pipeline = AuditPipeline(config=AgentConfig())
        result = pipeline.audit_file(path, language or None)
        return result, FileAuditTiming(
            source_file=str(path),
            elapsed_s=time.monotonic() - started,
            risk_markers=markers,
        )

    ctx = multiprocessing.get_context("spawn")
    queue: "multiprocessing.Queue[object]" = ctx.Queue()
    process = ctx.Process(
        target=_audit_worker, args=(str(path), language, queue), daemon=True
    )
    process.start()
    try:
        # Read before join: a large AuditResult can fill the pipe buffer, and a
        # child blocked on flushing it would otherwise look like a timeout.
        payload: object | None = queue.get(timeout=timeout_s)
    except Exception:
        payload = None
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=5)
        if process.is_alive():  # pragma: no cover - kill escalation
            process.kill()
            process.join(timeout=5)
        queue.close()

    elapsed = time.monotonic() - started
    if isinstance(payload, AuditResult):
        return payload, FileAuditTiming(
            source_file=str(path), elapsed_s=elapsed, risk_markers=markers
        )
    if isinstance(payload, BaseException):
        result = AuditResult(
            success=False,
            source_file=str(path),
            language=language,
            spec_extracted=False,
            verification_status="unverifiable",
            errors=[str(payload)],
        )
        return _finalize_audit_result(result), FileAuditTiming(
            source_file=str(path), elapsed_s=elapsed, risk_markers=markers
        )
    return _timeout_result(path, language, timeout_s, markers), FileAuditTiming(
        source_file=str(path),
        elapsed_s=elapsed,
        timed_out=True,
        risk_markers=markers,
    )


def format_timing_markdown(
    timings: list[FileAuditTiming], slow_threshold_s: float
) -> str:
    """Render the per-file timeout/slow-file section of the job summary."""
    timed_out = [timing for timing in timings if timing.timed_out]
    slow = [
        timing
        for timing in timings
        if not timing.timed_out and timing.elapsed_s >= slow_threshold_s > 0
    ]
    if not timed_out and not slow:
        return ""

    lines = [
        "#### per-file audit cost",
        "",
        "| file | seconds | timed out | risk markers |",
        "| --- | ---: | :---: | --- |",
    ]
    for timing in [*timed_out, *sorted(slow, key=lambda t: -t.elapsed_s)]:
        markers = ", ".join(timing.risk_markers) or "—"
        lines.append(
            f"| `{Path(timing.source_file).name}` | {timing.elapsed_s:.1f} | "
            f"{'yes' if timing.timed_out else 'no'} | {markers} |"
        )
    lines.append("")
    return "\n".join(lines)
