"""Pattern Library: stores and retrieves successful fix patterns.

Successful fixes are recorded as patterns keyed by violation_type.
When a new fix is needed, similar past patterns are retrieved and
injected into LLM prompts as few-shot examples.

Storage: JSON file at ~/.mumei-agent/patterns.json
"""
from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

# Default storage location
DEFAULT_PATTERN_DIR = Path.home() / ".mumei-agent"
DEFAULT_PATTERN_FILE = DEFAULT_PATTERN_DIR / "patterns.json"
MAX_PATTERNS_PER_TYPE = 20  # Keep at most N patterns per violation type
MAX_FEW_SHOT = 3  # Inject at most N examples into prompts


@dataclass
class FixPattern:
    """A single recorded fix pattern."""
    violation_type: str
    failure_type: str
    source_before: str
    source_after: str
    report_summary: dict  # Subset of report: violation_type, failure_type, counterexample, suggestion
    fix_method: str  # "rule_based" or "llm"
    content_hash: str  # SHA-256 of source_before to detect duplicates
    timestamp: str = ""
    applied_count: int = 0   # P6-B: how many times this pattern was applied
    success_count: int = 0   # P6-B: how many times application succeeded


@dataclass
class PatternLibrary:
    """In-memory pattern store backed by a JSON file."""
    patterns: dict[str, list[dict]] = field(default_factory=dict)  # violation_type -> list of pattern dicts
    storage_path: Path = DEFAULT_PATTERN_FILE

    def __post_init__(self) -> None:
        """Automatically load existing patterns from disk on creation."""
        self.load()

    def load(self) -> None:
        """Load patterns from disk."""
        if self.storage_path.exists():
            try:
                data = json.loads(self.storage_path.read_text(encoding="utf-8"))
                self.patterns = data if isinstance(data, dict) else {}
            except (json.JSONDecodeError, OSError):
                self.patterns = {}

    def save(self) -> None:
        """Persist patterns to disk."""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage_path.write_text(
            json.dumps(self.patterns, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def record(
        self,
        violation_type: str,
        failure_type: str,
        source_before: str,
        source_after: str,
        report: dict,
        fix_method: str = "llm",
    ) -> None:
        """Record a successful fix pattern."""
        content_hash = hashlib.sha256(source_before.encode()).hexdigest()[:16]

        # Deduplicate: skip if same source_before already recorded for this type
        existing = self.patterns.get(violation_type, [])
        if any(p.get("content_hash") == content_hash for p in existing):
            return

        report_summary = {
            k: report.get(k)
            for k in ("violation_type", "failure_type", "counterexample", "suggestion", "atom")
            if report.get(k) is not None
        }

        pattern = {
            "violation_type": violation_type,
            "failure_type": failure_type,
            "source_before": source_before,
            "source_after": source_after,
            "report_summary": report_summary,
            "fix_method": fix_method,
            "content_hash": content_hash,
            "applied_count": 0,
            "success_count": 0,
        }

        if violation_type not in self.patterns:
            self.patterns[violation_type] = []
        self.patterns[violation_type].append(pattern)

        # Trim to MAX_PATTERNS_PER_TYPE (keep most recent)
        if len(self.patterns[violation_type]) > MAX_PATTERNS_PER_TYPE:
            self.patterns[violation_type] = self.patterns[violation_type][-MAX_PATTERNS_PER_TYPE:]

        self.save()

    def lookup(self, violation_type: str, max_results: int = MAX_FEW_SHOT) -> list[dict]:
        """Retrieve the best patterns for a given violation type.

        Patterns are sorted by success rate (``success_count / max(applied_count, 1)``)
        in descending order so the most effective patterns appear first.
        """
        patterns = self.patterns.get(violation_type, [])
        # Sort by success rate descending (patterns that have never been
        # applied yet keep a rate of 0.0 and sort after proven ones).
        sorted_patterns = sorted(
            patterns,
            key=lambda p: p.get("success_count", 0) / max(p.get("applied_count", 0), 1),
            reverse=True,
        )
        return sorted_patterns[:max_results]

    def format_few_shot(self, violation_type: str) -> str:
        """Format retrieved patterns as few-shot examples for LLM prompts.

        Returns a string section that can be appended to prompts, or empty
        string if no patterns exist for this violation type.
        """
        patterns = self.lookup(violation_type)
        if not patterns:
            return ""

        lines = [f"# Past successful fixes for '{violation_type}' (use as reference):"]
        for i, p in enumerate(patterns, 1):
            lines.append(f"\n## Example {i}:")
            report_summary = p.get("report_summary", {})
            if report_summary.get("counterexample"):
                ce = report_summary["counterexample"]
                ce_str = ", ".join(f"{k}={v}" for k, v in ce.items()) if isinstance(ce, dict) else str(ce)
                lines.append(f"Counterexample: {ce_str}")
            if report_summary.get("suggestion"):
                lines.append(f"Suggestion: {report_summary['suggestion']}")
            lines.append(f"Before:\n```mumei\n{p['source_before']}\n```")
            lines.append(f"After (verified fix):\n```mumei\n{p['source_after']}\n```")
            fix_method = p.get("fix_method", "unknown")
            lines.append(f"Fix method: {fix_method}")

        return "\n".join(lines)

    def try_pattern_fix(
        self,
        violation_type: str,
        source_code: str,
        report: dict,
        mumei_client: "MumeiClient",
    ) -> str | None:
        """Attempt to fix *source_code* by applying a stored pattern.

        Patterns are tried in success-rate order.  For each candidate the
        transformation encoded by ``source_before`` → ``source_after`` is
        applied analogously to *source_code*.  The result is verified via
        ``mumei_client.verify()``.

        Returns the fixed code on success, or ``None`` if no pattern
        produced a verified fix.
        """
        import difflib
        import tempfile

        candidates = self.lookup(violation_type, max_results=MAX_PATTERNS_PER_TYPE)
        if not candidates:
            return None

        for pattern in candidates:
            # Similarity check: same violation_type is already guaranteed by
            # lookup.  Additionally check that the counterexample structure
            # or suggestion text overlaps.
            pat_summary = pattern.get("report_summary", {})
            pat_ce = pat_summary.get("counterexample")
            rep_ce = report.get("counterexample")
            pat_sug = pat_summary.get("suggestion", "")
            rep_sug = report.get("suggestion", "")

            # Quick relevance filter: require at least one of counterexample
            # structure match or suggestion similarity.
            ce_match = (
                pat_ce is not None
                and rep_ce is not None
                and isinstance(pat_ce, dict)
                and isinstance(rep_ce, dict)
                and set(pat_ce.keys()) == set(rep_ce.keys())
            )
            sug_match = bool(pat_sug and rep_sug and pat_sug == rep_sug)
            if not ce_match and not sug_match:
                continue

            # Build an analogous transformation using unified diff
            before_lines = pattern.get("source_before", "").splitlines(keepends=True)
            after_lines = pattern.get("source_after", "").splitlines(keepends=True)
            diff = list(difflib.unified_diff(before_lines, after_lines, n=0))
            if not diff:
                continue

            # Try to apply the diff to current source_code
            candidate_code = self._apply_pattern_diff(
                source_code, before_lines, after_lines,
            )
            if candidate_code is None or candidate_code == source_code:
                continue

            # Increment applied_count
            pattern["applied_count"] = pattern.get("applied_count", 0) + 1

            # Verify the candidate
            tmp_path: str | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".mm", delete=False, encoding="utf-8",
                ) as tmp:
                    tmp_path = tmp.name
                    tmp.write(candidate_code)
                result = mumei_client.verify(tmp_path)
                if result["success"]:
                    pattern["success_count"] = pattern.get("success_count", 0) + 1
                    self.save()
                    return candidate_code
            except Exception:
                pass
            finally:
                try:
                    if tmp_path:
                        Path(tmp_path).unlink(missing_ok=True)
                except Exception:
                    pass

        # Persist updated applied_count values even when no pattern succeeded
        self.save()
        return None

    @staticmethod
    def _apply_pattern_diff(
        source_code: str,
        before_lines: list[str],
        after_lines: list[str],
    ) -> str | None:
        """Try to apply the transformation encoded by before→after to *source_code*.

        Uses a simple line-level matching strategy: find consecutive lines in
        *source_code* that match *before_lines* (stripped) and replace them
        with *after_lines*.
        """
        src_lines = source_code.splitlines(keepends=True)
        before_stripped = [l.strip() for l in before_lines]
        n = len(before_stripped)
        if n == 0:
            return None

        for i in range(len(src_lines) - n + 1):
            window = [l.strip() for l in src_lines[i:i + n]]
            if window == before_stripped:
                # Replace
                result = src_lines[:i] + after_lines + src_lines[i + n:]
                return "".join(result)
        return None

    @property
    def total_patterns(self) -> int:
        return sum(len(v) for v in self.patterns.values())

    def stats(self) -> dict:
        """Return pattern counts per violation type."""
        return {vt: len(patterns) for vt, patterns in self.patterns.items()}
