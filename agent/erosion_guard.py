"""Read-only contract-erosion guard for repair candidates."""
from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ErosionOutcome:
    passed: bool
    skipped: bool
    summary: str
    report: dict | None


@dataclass
class ErosionGuard:
    baseline_path: Path
    _temporary_directory: tempfile.TemporaryDirectory
    _original_bytes: bytes
    _warned_unavailable: bool = False

    @classmethod
    def create(cls, source_file: str | Path) -> ErosionGuard:
        source_path = Path(source_file).expanduser().resolve()
        original_bytes = source_path.read_bytes()
        temporary_directory = tempfile.TemporaryDirectory(
            prefix="mumei-erosion-"
        )
        baseline_path = Path(temporary_directory.name) / source_path.name
        baseline_path.write_bytes(original_bytes)
        return cls(
            baseline_path=baseline_path,
            _temporary_directory=temporary_directory,
            _original_bytes=original_bytes,
        )

    def close(self) -> None:
        self._temporary_directory.cleanup()

    def restore(self, source_file: str | Path) -> None:
        Path(source_file).write_bytes(self._original_bytes)

    def check(self, mumei_client: Any, source_file: str | Path) -> ErosionOutcome:
        try:
            result = mumei_client.erosion_check(
                str(Path(source_file).expanduser().resolve()),
                str(self.baseline_path),
            )
        except Exception:
            return ErosionOutcome(
                passed=False,
                skipped=False,
                summary="erosion check returned malformed output",
                report=None,
            )

        if not isinstance(result, dict):
            return ErosionOutcome(
                passed=False,
                skipped=False,
                summary="erosion check returned malformed output",
                report=None,
            )

        returncode = result.get("returncode")
        report = result.get("report")
        if not isinstance(report, dict):
            report = None
        stderr = str(result.get("stderr") or "").strip()

        if returncode == 2 and "unrecognized subcommand" in stderr.lower():
            if not self._warned_unavailable:
                print(
                    "mumei erosion unavailable; skipping contract erosion check",
                    file=sys.stderr,
                )
                self._warned_unavailable = True
            return ErosionOutcome(
                passed=True,
                skipped=True,
                summary="mumei erosion unavailable; skipping contract erosion check",
                report=None,
            )

        if returncode == 4:
            summary = "source cannot serve as an erosion baseline; skipping contract erosion check"
            if stderr:
                summary = f"{summary}: {stderr}"
            print(f"Warning: {summary}", file=sys.stderr)
            return ErosionOutcome(True, True, summary, None)

        if returncode == 0 and report is not None:
            return ErosionOutcome(True, False, "contract erosion check passed", report)

        if returncode == 1 and report is not None and report.get("status") == "fail":
            return ErosionOutcome(
                False,
                False,
                _erosion_summary(report),
                report,
            )

        return ErosionOutcome(
            passed=False,
            skipped=False,
            summary="erosion check returned malformed output",
            report=report,
        )


def create_guard(
    source_file: str | Path,
    *,
    enabled: bool,
) -> ErosionGuard | None:
    if not enabled or not Path(source_file).expanduser().is_file():
        return None
    return ErosionGuard.create(source_file)


def _erosion_summary(report: dict) -> str:
    atoms = report.get("atoms")
    failures: list[str] = []
    if isinstance(atoms, list):
        for atom in atoms:
            if not isinstance(atom, dict):
                continue
            status = str(atom.get("status") or "")
            if status in {"preserved", "strengthened", "refined"}:
                continue
            name = str(atom.get("name") or "<unknown>")
            detail = atom.get("detail")
            failure = f"{name}: {status or 'failed'}"
            if detail:
                failure += f" ({detail})"
            counterexample = atom.get("counterexample")
            if counterexample is not None:
                failure += (
                    " counterexample: "
                    + json.dumps(counterexample, sort_keys=True, ensure_ascii=False)
                )
            failures.append(failure)
    return "; ".join(failures) or "contract erosion detected"


def structured_feedback(outcome: ErosionOutcome) -> dict[str, object]:
    report = outcome.report or {}
    atoms = report.get("atoms")
    loss_vector: list[dict[str, object]] = []
    if isinstance(atoms, list):
        for atom in atoms:
            if not isinstance(atom, dict):
                continue
            status = str(atom.get("status") or "")
            if status in {"preserved", "strengthened", "refined"}:
                continue
            name = str(atom.get("name") or "<unknown>")
            detail = str(atom.get("detail") or status or "contract weakened")
            loss_vector.append(
                {
                    "violated_property": f"{name}: {detail}",
                    "counter_example": atom.get("counterexample"),
                }
            )
    if not loss_vector:
        loss_vector.append(
            {
                "violated_property": outcome.summary,
                "counter_example": None,
            }
        )
    return {
        "status": "verification_failed",
        "error_type": "contract_erosion",
        "location": None,
        "reconstruction_loss": {
            "loss_set_size": len(loss_vector),
            "is_zero_loss": False,
            "loss_vector": loss_vector,
        },
        "feedback_instruction": outcome.summary,
    }
