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


@dataclass
class PatternLibrary:
    """In-memory pattern store backed by a JSON file."""
    patterns: dict[str, list[dict]] = field(default_factory=dict)  # violation_type -> list of pattern dicts
    storage_path: Path = DEFAULT_PATTERN_FILE

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
        }

        if violation_type not in self.patterns:
            self.patterns[violation_type] = []
        self.patterns[violation_type].append(pattern)

        # Trim to MAX_PATTERNS_PER_TYPE (keep most recent)
        if len(self.patterns[violation_type]) > MAX_PATTERNS_PER_TYPE:
            self.patterns[violation_type] = self.patterns[violation_type][-MAX_PATTERNS_PER_TYPE:]

        self.save()

    def lookup(self, violation_type: str, max_results: int = MAX_FEW_SHOT) -> list[dict]:
        """Retrieve the most recent patterns for a given violation type."""
        patterns = self.patterns.get(violation_type, [])
        # Return most recent N patterns
        return patterns[-max_results:]

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

    @property
    def total_patterns(self) -> int:
        return sum(len(v) for v in self.patterns.values())

    def stats(self) -> dict:
        """Return pattern counts per violation type."""
        return {vt: len(patterns) for vt, patterns in self.patterns.items()}
