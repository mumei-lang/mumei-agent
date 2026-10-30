"""Negative-control gate for generated Mumei atoms."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, Iterable


_STATUSES = {
    "discriminating",
    "weak",
    "inconclusive",
    "no_mutants",
    "not_checked",
}


@dataclass
class ControlsOutcome:
    passed: bool
    skipped: bool
    summary: str
    atoms: dict[str, dict[str, Any]]
    malformed: bool = False
    unavailable: bool = False


class ControlsGate:
    def __init__(self, mode: str) -> None:
        if mode not in {"off", "warn", "require"}:
            raise ValueError(
                f"invalid controls gate mode {mode!r}; choose off, warn, or require"
            )
        self.mode = mode

    def check(
        self,
        mumei_client: Any,
        path: str,
        atom_names: Iterable[str | None],
    ) -> ControlsOutcome:
        raw_names = list(atom_names)
        has_unnamed = any(
            not isinstance(name, str) or not name.strip()
            for name in raw_names
        )
        names = list(
            dict.fromkeys(
                name for name in raw_names
                if isinstance(name, str) and name.strip()
            )
        )
        if not names:
            summary = "controls cannot check unnamed atom(s)"
            if self.mode == "warn":
                print(f"WARNING: {summary}", file=sys.stderr)
            return ControlsOutcome(
                passed=self.mode != "require",
                skipped=True,
                summary=summary,
                atoms={},
                malformed=True,
            )
        if has_unnamed and self.mode == "require":
            return ControlsOutcome(
                passed=False,
                skipped=True,
                summary="controls cannot check unnamed atom(s)",
                atoms={},
                malformed=True,
            )

        atoms: dict[str, dict[str, Any]] = {}
        malformed: list[str] = []
        unavailable: list[str] = []
        controls_unavailable = False

        for name in names:
            if controls_unavailable:
                unavailable.append(
                    f"{name}: not checked after controls became unavailable"
                )
                continue
            try:
                result = mumei_client.controls_check(path, atom=name)
            except Exception as exc:
                stderr_text = str(getattr(exc, "stderr", "") or "")
                malformed.append(
                    f"{name}: exception {type(exc).__name__}: {exc}; "
                    f"stderr: {stderr_text}"
                )
                continue

            if not isinstance(result, dict):
                malformed.append(f"{name}: response is not an object; stderr: ")
                continue

            stderr = result.get("stderr")
            stderr_text = stderr if isinstance(stderr, str) else str(stderr or "")
            returncode = result.get("returncode")
            if (
                returncode == 2
                and "unrecognized subcommand" in stderr_text.lower()
            ):
                unavailable.append(f"{name}: {stderr_text}")
                controls_unavailable = True
                continue

            report = result.get("report")
            if returncode not in (0, 1):
                malformed.append(
                    f"{name}: unexpected exit code {returncode}; stderr: {stderr_text}"
                )
                continue
            if not isinstance(report, dict):
                malformed.append(
                    f"{name}: report is not an object; stderr: {stderr_text}"
                )
                continue

            entries = report.get("atoms")
            atom_report = None
            if isinstance(entries, list):
                atom_report = next(
                    (
                        entry for entry in entries
                        if isinstance(entry, dict) and entry.get("name") == name
                    ),
                    None,
                )
            if atom_report is None:
                malformed.append(
                    f"{name}: report has no matching atom entry; stderr: {stderr_text}"
                )
                continue

            status = atom_report.get("status")
            mutants = atom_report.get("mutants")
            count_fields = ("tested", "killed", "survived", "unanalyzable")
            counts = {field: atom_report.get(field) for field in count_fields}
            if (
                not isinstance(status, str)
                or status not in _STATUSES
                or not isinstance(mutants, list)
                or any(
                    not isinstance(mutant, dict)
                    or not isinstance(mutant.get("id"), str)
                    or not isinstance(mutant.get("outcome"), str)
                    for mutant in mutants
                )
                or any(
                    not isinstance(value, int) or isinstance(value, bool)
                    for value in counts.values()
                )
            ):
                malformed.append(
                    f"{name}: malformed atom entry; stderr: {stderr_text}"
                )
                continue
            if counts["tested"] != sum(
                counts[field] for field in ("killed", "survived", "unanalyzable")
            ):
                malformed.append(
                    f"{name}: inconsistent mutant counts; stderr: {stderr_text}"
                )
                continue

            surviving = [
                mutant["id"]
                for mutant in mutants
                if isinstance(mutant, dict)
                and mutant.get("outcome") == "survived"
                and isinstance(mutant.get("id"), str)
            ]
            atoms[name] = {
                "status": status,
                **counts,
                "surviving": surviving,
            }

        weak_atoms = {
            name: atom for name, atom in atoms.items()
            if atom["status"] in {"weak", "inconclusive"}
        }
        unavailable = list(dict.fromkeys(unavailable))
        messages: list[str] = []
        if has_unnamed:
            messages.append("controls cannot check unnamed atom(s)")
        if weak_atoms:
            failures = []
            for name, atom in weak_atoms.items():
                surviving = ", ".join(atom["surviving"])
                failures.append(
                    f"{name}: {surviving or atom['status']}"
                )
            messages.append("weak specification: " + "; ".join(failures))
        if unavailable:
            messages.append("controls unavailable: " + "; ".join(unavailable))
        if malformed:
            messages.append("controls check malformed: " + "; ".join(malformed))

        if not messages:
            summary = f"negative controls passed for {len(atoms)} atom(s)"
        else:
            summary = "; ".join(messages)

        if self.mode == "warn" and messages:
            print(f"WARNING: {summary}", file=sys.stderr)

        return ControlsOutcome(
            passed=self.mode == "warn" or not messages,
            skipped=has_unnamed or bool(unavailable),
            summary=summary,
            atoms=atoms,
            malformed=has_unnamed or bool(malformed),
            unavailable=bool(unavailable),
        )
