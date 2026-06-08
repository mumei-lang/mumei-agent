"""Human-review queue tracking for Mumei proof obligations."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Mapping


JsonDict = dict[str, object]


class ReviewStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    ESCALATED_TO_LEAN = "escalated_to_lean"
    REJECTED = "rejected"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _coerce_atoms(value: object) -> list[JsonDict]:
    if not isinstance(value, list):
        return []
    atoms: list[JsonDict] = []
    for item in value:
        if isinstance(item, dict):
            atoms.append(dict(item))
    return atoms


@dataclass
class HumanReviewTracker:
    queue_path: Path
    mumei_repo: Path | None = None
    data: JsonDict = field(default_factory=dict)

    @classmethod
    def from_repo(cls, mumei_repo: str | Path) -> "HumanReviewTracker":
        repo = Path(mumei_repo).expanduser().resolve()
        return cls(repo / "human_review_queue.json", repo)

    @classmethod
    def default(cls) -> "HumanReviewTracker":
        queue = os.environ.get("MUMEI_HUMAN_REVIEW_QUEUE")
        if queue:
            return cls(Path(queue).expanduser().resolve())
        repo = os.environ.get("MUMEI_REPO")
        if repo:
            return cls.from_repo(repo)
        return cls(Path("human_review_queue.json").resolve())

    def load(self) -> JsonDict:
        if not self.queue_path.exists():
            self.data = {
                "version": "1.0",
                "file": "",
                "atoms": [],
                "review_history": [],
            }
            return self.data
        payload = json.loads(self.queue_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"review queue must be a JSON object: {self.queue_path}")
        payload = dict(payload)
        atoms = _coerce_atoms(payload.get("atoms"))
        for atom in atoms:
            atom.setdefault("status", ReviewStatus.PENDING.value)
        payload["atoms"] = atoms
        if not isinstance(payload.get("review_history"), list):
            payload["review_history"] = []
        self.data = payload
        return self.data

    def save(self) -> None:
        if not self.data:
            self.load()
        self.queue_path.parent.mkdir(parents=True, exist_ok=True)
        self.queue_path.write_text(
            json.dumps(self.data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def atoms(self) -> list[JsonDict]:
        if not self.data:
            self.load()
        return _coerce_atoms(self.data.get("atoms"))

    def queue(self) -> JsonDict:
        if not self.data:
            self.load()
        self.data["atoms"] = self.atoms()
        return self.data

    def approve_review(self, atom_name: str, reviewer: str, notes: str) -> JsonDict:
        return self._record_decision(atom_name, ReviewStatus.APPROVED, reviewer, notes)

    def reject_review(self, atom_name: str, reviewer: str, notes: str) -> JsonDict:
        return self._record_decision(atom_name, ReviewStatus.REJECTED, reviewer, notes)

    def _record_decision(
        self, atom_name: str, status: ReviewStatus, reviewer: str, notes: str,
    ) -> JsonDict:
        entry = self._find_atom(atom_name)
        timestamp = _utc_now()
        entry["status"] = status.value
        entry["reviewer"] = reviewer
        entry["notes"] = notes
        entry["reviewed_at"] = timestamp
        self._append_history(
            {
                "atom_name": atom_name,
                "status": status.value,
                "reviewer": reviewer,
                "notes": notes,
                "timestamp": timestamp,
            }
        )
        self.save()
        return entry

    def escalate_to_lean(self, atom_name: str) -> JsonDict:
        entry = self._find_atom(atom_name)
        command = self._lean_escalation_command()
        proc = subprocess.run(
            command,
            cwd=str(self._repo_root()),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        timestamp = _utc_now()
        entry["status"] = ReviewStatus.ESCALATED_TO_LEAN.value
        entry["escalated_at"] = timestamp
        entry["lean_escalation"] = {
            "command": command,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
        self._append_history(
            {
                "atom_name": atom_name,
                "status": ReviewStatus.ESCALATED_TO_LEAN.value,
                "timestamp": timestamp,
                "command": command,
                "returncode": proc.returncode,
            }
        )
        self.save()
        return entry

    def _find_atom(self, atom_name: str) -> JsonDict:
        atoms = self.atoms()
        for atom in atoms:
            name = atom.get("name", atom.get("atom_name"))
            if name == atom_name:
                self.data["atoms"] = atoms
                return atom
        raise KeyError(f"atom not found in human review queue: {atom_name}")

    def _append_history(self, event: Mapping[str, object]) -> None:
        history = self.data.get("review_history")
        if not isinstance(history, list):
            history = []
        history.append(dict(event))
        self.data["review_history"] = history

    def _repo_root(self) -> Path:
        if self.mumei_repo is not None:
            return self.mumei_repo
        env_repo = os.environ.get("MUMEI_REPO")
        if env_repo:
            return Path(env_repo).expanduser().resolve()
        return self.queue_path.parent

    def _source_file(self) -> Path:
        if not self.data:
            self.load()
        value = self.data.get("source_file", self.data.get("file"))
        if not isinstance(value, str) or not value.strip():
            raise ValueError("human review queue does not record source_file or file")
        path = Path(value).expanduser()
        if path.is_absolute():
            return path
        return self._repo_root() / path

    def _lean_escalation_command(self) -> list[str]:
        source_file = str(self._source_file())
        mumei_bin = os.environ.get("MUMEI_BIN")
        if mumei_bin:
            return [
                mumei_bin,
                "verify",
                source_file,
                "--escalate-lean",
                "--emit",
                "escalation-bundle",
            ]
        return [
            "cargo",
            "run",
            "--quiet",
            "--",
            "verify",
            source_file,
            "--escalate-lean",
            "--emit",
            "escalation-bundle",
        ]
