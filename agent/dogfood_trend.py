"""Verdict-bucket time series for the dogfood corpus gate.

The gate already reports the current run's `refuted` / `unverifiable` /
`verified` counts.  Continuous dogfooding additionally needs to notice *change*:
a sudden jump in `refuted` (a regression in the audit pipeline or a newly added
corpus file that genuinely fails) and a skew inside the `unverifiable` cause
subcategories (e.g. everything collapsing into `timeout` because the CI budget
shrank).

The verdict vocabulary is fixed: this module only counts the existing verdicts
and the existing `unverifiable` subcategories, and never introduces a new one.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path

#: `refuted` must grow by at least this many files before a spike is reported,
#: so a single new refuted file in a tiny corpus is not an alert.
DEFAULT_SPIKE_MIN_DELTA = 2
#: ... and by at least this ratio over the recent baseline.
DEFAULT_SPIKE_RATIO = 0.5
#: An `unverifiable` cause holding at least this share of all unverifiable
#: files is a skew candidate.
DEFAULT_SKEW_SHARE = 0.6
#: ... and it is only reported when the share grew by at least this much.
DEFAULT_SKEW_SHARE_DELTA = 0.2
#: Snapshots kept in the history file.
DEFAULT_HISTORY_LIMIT = 30


@dataclass
class VerdictSnapshot:
    """One run's verdict buckets, as recorded in the history file."""

    timestamp: str
    run_id: str
    total_files: int
    refuted: int
    verified: int
    unverifiable: int
    unverifiable_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation of the snapshot."""
        return asdict(self)


def snapshot_from_totals(
    totals: dict[str, object], run_id: str, timestamp: str | None = None
) -> VerdictSnapshot:
    """Build a snapshot from the gate's combined totals block."""
    counts = totals.get("unverifiable_counts") or {}
    return VerdictSnapshot(
        timestamp=timestamp
        or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        run_id=run_id,
        total_files=int(totals.get("total_files") or 0),
        refuted=int(totals.get("human_review_count") or 0),
        verified=int(totals.get("verified_count") or 0),
        unverifiable=int(totals.get("unverifiable_count") or 0),
        unverifiable_counts={
            str(category): int(count) for category, count in dict(counts).items()
        },
    )


def load_history(path: Path) -> list[VerdictSnapshot]:
    """Read the snapshot history, tolerating a missing or corrupt file.

    A corrupt history must not fail the gate: dogfooding is advisory, and the
    file is restored from a best-effort CI cache.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    history: list[VerdictSnapshot] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        try:
            history.append(
                VerdictSnapshot(
                    timestamp=str(entry["timestamp"]),
                    run_id=str(entry.get("run_id", "")),
                    total_files=int(entry.get("total_files") or 0),
                    refuted=int(entry.get("refuted") or 0),
                    verified=int(entry.get("verified") or 0),
                    unverifiable=int(entry.get("unverifiable") or 0),
                    unverifiable_counts={
                        str(category): int(count)
                        for category, count in dict(
                            entry.get("unverifiable_counts") or {}
                        ).items()
                    },
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return history


def save_history(
    path: Path,
    history: list[VerdictSnapshot],
    limit: int = DEFAULT_HISTORY_LIMIT,
) -> None:
    """Write the most recent ``limit`` snapshots to ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            [snapshot.to_dict() for snapshot in history[-limit:]],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _baseline(values: list[int]) -> float:
    return sum(values) / len(values) if values else 0.0


def detect_refuted_spike(
    history: list[VerdictSnapshot],
    *,
    min_delta: int = DEFAULT_SPIKE_MIN_DELTA,
    ratio: float = DEFAULT_SPIKE_RATIO,
) -> list[str]:
    """Return alerts when the latest run's `refuted` count jumps.

    The baseline is the mean of the preceding snapshots, so one noisy run does
    not permanently raise the bar.
    """
    if len(history) < 2:
        return []
    latest, previous = history[-1], history[:-1]
    baseline = _baseline([snapshot.refuted for snapshot in previous])
    delta = latest.refuted - baseline
    if delta < min_delta or delta < baseline * ratio:
        return []
    return [
        f"refuted spike: {latest.refuted} file(s) refuted vs baseline "
        f"{baseline:.1f} over the previous {len(previous)} run(s)"
    ]


def detect_unverifiable_skew(
    history: list[VerdictSnapshot],
    *,
    share_threshold: float = DEFAULT_SKEW_SHARE,
    share_delta: float = DEFAULT_SKEW_SHARE_DELTA,
) -> list[str]:
    """Return alerts when one `unverifiable` cause starts dominating."""
    if len(history) < 2:
        return []
    latest, previous = history[-1], history[:-1]
    if latest.unverifiable <= 0:
        return []

    alerts: list[str] = []
    for category, count in sorted(latest.unverifiable_counts.items()):
        share = count / latest.unverifiable
        if share < share_threshold:
            continue
        baseline_shares = [
            snapshot.unverifiable_counts.get(category, 0) / snapshot.unverifiable
            for snapshot in previous
            if snapshot.unverifiable > 0
        ]
        baseline = _baseline([int(round(s * 100)) for s in baseline_shares]) / 100
        if share - baseline < share_delta:
            continue
        alerts.append(
            f"unverifiable skew: `{category}` holds {share:.0%} of "
            f"{latest.unverifiable} unverifiable file(s) vs baseline {baseline:.0%}"
        )
    return alerts


def format_trend_markdown(
    history: list[VerdictSnapshot], alerts: list[str]
) -> str:
    """Render the verdict time series and any alerts for the job summary."""
    if not history:
        return ""
    lines = [
        "### Dogfood verdict time series",
        "",
        "| run | files | refuted | unverifiable | verified |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for snapshot in history:
        label = f"{snapshot.timestamp} ({snapshot.run_id})" if snapshot.run_id else snapshot.timestamp
        lines.append(
            f"| {label} | {snapshot.total_files} | {snapshot.refuted} | "
            f"{snapshot.unverifiable} | {snapshot.verified} |"
        )
    lines.append("")

    latest = history[-1]
    if latest.unverifiable_counts:
        lines += [
            "#### latest unverifiable causes",
            "",
            "| cause | files | share |",
            "| --- | ---: | ---: |",
        ]
        for category, count in sorted(latest.unverifiable_counts.items()):
            share = count / latest.unverifiable if latest.unverifiable else 0.0
            lines.append(f"| {category} | {count} | {share:.0%} |")
        lines.append("")

    if alerts:
        lines += ["#### trend alerts", ""]
        lines += [f"- {alert}" for alert in alerts]
        lines.append("")
    return "\n".join(lines)
