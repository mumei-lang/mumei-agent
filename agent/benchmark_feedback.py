"""P16 benchmark results as vStd forge / proliferate input.

``benchmarks/run_benchmarks.py --forge-feedback <path>`` in the mumei repository
emits a ``mumei.benchmark_forge_feedback/v1`` document that scores each
benchmark category by expected-outcome success rate, counterexample catch rate,
trusted ratio, and Z3 / Lean solver time. This module turns that document into a
priority bias over gap proposals and forge task specs, so the categories the
benchmark suite is weakest on pull their stdlib domains forward in the
proliferation queue.

Priority is "lower runs first", so a weak domain contributes a negative
``priority_delta``. Feedback never adds or removes work: it only reorders
proposals that gap analysis already produced, and records its provenance on each
affected item.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SCHEMA = "mumei.benchmark_forge_feedback/v1"


@dataclass(frozen=True)
class DomainBias:
    domain: str
    priority_delta: int
    weakness_score: float
    driving_category: str


@dataclass(frozen=True)
class BenchmarkFeedback:
    """A parsed ``mumei.benchmark_forge_feedback/v1`` document."""

    timestamp: str
    stdlib_trusted_ratio: float | None
    weak_categories: tuple[str, ...]
    domain_bias: tuple[DomainBias, ...]
    categories: tuple[dict[str, Any], ...] = field(default=())
    source_path: str | None = None

    @classmethod
    def from_dict(
        cls, payload: dict[str, Any], *, source_path: str | None = None
    ) -> "BenchmarkFeedback":
        schema = payload.get("schema")
        if schema != SCHEMA:
            raise ValueError(f"unsupported benchmark feedback schema: {schema!r}")
        bias = tuple(
            DomainBias(
                domain=str(entry["domain"]),
                priority_delta=int(entry["priority_delta"]),
                weakness_score=float(entry["weakness_score"]),
                driving_category=str(entry.get("driving_category", "")),
            )
            for entry in payload.get("domain_bias", [])
        )
        return cls(
            timestamp=str(payload.get("timestamp", "")),
            stdlib_trusted_ratio=payload.get("stdlib_trusted_ratio"),
            weak_categories=tuple(payload.get("weak_categories", [])),
            domain_bias=bias,
            categories=tuple(payload.get("categories", [])),
            source_path=source_path,
        )

    @classmethod
    def load(cls, path: str | Path) -> "BenchmarkFeedback":
        resolved = Path(path)
        payload = json.loads(resolved.read_text(encoding="utf-8"))
        return cls.from_dict(payload, source_path=str(resolved))

    def bias_for(self, target: str) -> DomainBias | None:
        """Return the bias for ``target`` (e.g. ``std/math/abs.mm``).

        The longest matching domain prefix wins, so ``std/math/abs.mm`` prefers a
        ``std/math`` entry over a ``std`` entry.
        """
        normalized = target.replace("\\", "/").lstrip("./")
        best: DomainBias | None = None
        for entry in self.domain_bias:
            domain = entry.domain.rstrip("/")
            if normalized == domain or normalized.startswith(domain + "/") or (
                normalized.startswith(domain) and normalized[len(domain):].startswith(".")
            ):
                if best is None or len(entry.domain) > len(best.domain):
                    best = entry
        return best

    def rank_proposals(
        self, proposals: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Reorder ``proposals`` by benchmark weakness, preserving membership.

        Ties keep the incoming (gap-analysis) order, so feedback only breaks
        ties introduced by the benchmark signal.
        """
        annotated: list[tuple[int, int, dict[str, Any]]] = []
        for index, proposal in enumerate(proposals):
            bias = self.bias_for(str(proposal.get("name", "")))
            delta = bias.priority_delta if bias else 0
            if bias is not None:
                proposal["benchmark_feedback"] = {
                    "domain": bias.domain,
                    "priority_delta": bias.priority_delta,
                    "weakness_score": bias.weakness_score,
                    "driving_category": bias.driving_category,
                    "timestamp": self.timestamp,
                }
            annotated.append((delta, index, proposal))
        annotated.sort(key=lambda item: (item[0], item[1]))
        ranked = [proposal for _, _, proposal in annotated]
        for position, proposal in enumerate(ranked, start=1):
            if "priority" in proposal:
                proposal["priority"] = position
        return ranked

    def apply_to_specs(
        self, specs: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Bias forge task-spec priorities and reorder by effective priority."""
        for spec in specs:
            bias = self.bias_for(str(spec.get("target_file", "")))
            if bias is None:
                continue
            current = spec.get("priority")
            if isinstance(current, int):
                spec["priority"] = current + bias.priority_delta
            spec["benchmark_feedback"] = {
                "domain": bias.domain,
                "priority_delta": bias.priority_delta,
                "weakness_score": bias.weakness_score,
                "driving_category": bias.driving_category,
                "timestamp": self.timestamp,
            }
        return sorted(
            specs,
            key=lambda spec: spec.get("priority")
            if isinstance(spec.get("priority"), int)
            else 0,
        )

    def summary(self) -> dict[str, Any]:
        """Run-summary payload recorded alongside proliferate metrics."""
        return {
            "schema": SCHEMA,
            "source_path": self.source_path,
            "timestamp": self.timestamp,
            "stdlib_trusted_ratio": self.stdlib_trusted_ratio,
            "weak_categories": list(self.weak_categories),
            "domain_bias": [
                {
                    "domain": entry.domain,
                    "priority_delta": entry.priority_delta,
                    "weakness_score": entry.weakness_score,
                    "driving_category": entry.driving_category,
                }
                for entry in self.domain_bias
            ],
        }


def load_benchmark_feedback(
    path: str | Path | None,
) -> BenchmarkFeedback | None:
    """Load feedback, degrading to ``None`` when unavailable or malformed.

    The proliferation loop must run without benchmark input, so a missing or
    unreadable document is logged and ignored rather than raised.
    """
    if not path:
        return None
    try:
        return BenchmarkFeedback.load(path)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        json.JSONDecodeError,
    ):
        logger.warning("Ignoring unusable benchmark feedback at %s", path, exc_info=True)
        return None
