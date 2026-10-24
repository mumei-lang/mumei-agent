"""Read-only guard for source files pinned by a Mumei charter lock."""
from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOCK_SCHEMA = "mumei.charter-lock/v1"


@dataclass
class CharterOutcome:
    passed: bool
    summary: str
    report: dict | None


@dataclass
class CharterGuard:
    root: Path
    lock_path: Path
    snapshot: dict[str, str]

    @classmethod
    def discover(
        cls,
        source_file: str,
        lock_arg: str | None = None,
    ) -> CharterGuard | None:
        source_dir = Path(source_file).expanduser().resolve().parent
        directories: list[Path] = []
        directory = source_dir
        manifest_path: Path | None = None
        while True:
            directories.append(directory)
            candidate = directory / "mumei.toml"
            if candidate.is_file():
                manifest_path = candidate
                break
            if directory.parent == directory:
                break
            directory = directory.parent

        if lock_arg is not None:
            lock_path = Path(lock_arg).expanduser()
            if not lock_path.is_absolute():
                lock_path = Path.cwd() / lock_path
            if not lock_path.is_file():
                raise ValueError(f"charter lock does not exist: {lock_path}")
            root = manifest_path.parent if manifest_path is not None else lock_path.parent
            return cls._from_lock(lock_path, root)

        if manifest_path is not None:
            try:
                manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
                raise ValueError(f"could not parse {manifest_path}: {exc}") from exc
            charter = manifest.get("charter", {})
            if not isinstance(charter, dict):
                raise ValueError(f"invalid [charter] section in {manifest_path}")
            configured_lock = charter.get("lock")
            if configured_lock is not None and not isinstance(configured_lock, str):
                raise ValueError(f"[charter].lock must be a path in {manifest_path}")
            if configured_lock:
                lock_path = Path(configured_lock).expanduser()
                if not lock_path.is_absolute():
                    lock_path = manifest_path.parent / lock_path
            else:
                lock_path = manifest_path.parent / "charter.lock"
            if not lock_path.is_file():
                return None
            return cls._from_lock(lock_path, manifest_path.parent)

        lock_path = next(
            (path / "charter.lock" for path in directories if (path / "charter.lock").is_file()),
            None,
        )
        if lock_path is None:
            return None
        return cls._from_lock(lock_path, lock_path.parent)

    @classmethod
    def _from_lock(cls, lock_path: Path, root: Path | None = None) -> CharterGuard:
        lock_path = lock_path.resolve()
        root = root.resolve() if root is not None else lock_path.parent
        try:
            lock_bytes = lock_path.read_bytes()
            lock = json.loads(lock_bytes)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"could not parse charter lock {lock_path}: {exc}") from exc
        if not isinstance(lock, dict) or lock.get("schema") != LOCK_SCHEMA:
            raise ValueError(f"unsupported charter lock schema in {lock_path}")
        charters = lock.get("charters")
        if not isinstance(charters, list):
            raise ValueError(f"invalid charters list in {lock_path}")

        snapshot = {str(lock_path): hashlib.sha256(lock_bytes).hexdigest()}
        for entry in charters:
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                raise ValueError(f"invalid charter entry in {lock_path}")
            charter_path = Path(entry["path"])
            if not charter_path.is_absolute():
                charter_path = root / charter_path
            charter_path = charter_path.resolve()
            try:
                charter_bytes = charter_path.read_bytes()
            except OSError as exc:
                raise ValueError(
                    f"could not read charter {charter_path}: {exc}"
                ) from exc
            snapshot[str(charter_path)] = hashlib.sha256(charter_bytes).hexdigest()
        return cls(root=root, lock_path=lock_path, snapshot=snapshot)

    def is_charter_file(self, path: str) -> bool:
        candidate = str(Path(path).expanduser().resolve())
        return candidate in self.snapshot and candidate != str(self.lock_path)

    def tampered(self) -> list[str]:
        changed: list[str] = []
        for path, expected_hash in self.snapshot.items():
            try:
                current_hash = hashlib.sha256(Path(path).read_bytes()).hexdigest()
            except OSError:
                changed.append(path)
                continue
            if current_hash != expected_hash:
                changed.append(path)
        return sorted(changed)

    def check(self, mumei_client: Any, source_file: str) -> CharterOutcome:
        try:
            result = mumei_client.charter_check(
                str(Path(source_file).expanduser().resolve()),
                str(self.lock_path),
                cwd=self.root,
            )
        except Exception as exc:
            return CharterOutcome(
                passed=False,
                summary=f"charter check unavailable: {exc}",
                report=None,
            )

        if not isinstance(result, dict):
            return CharterOutcome(
                passed=False,
                summary="charter check returned an invalid result",
                report=None,
            )
        report = result.get("report")
        if not isinstance(report, dict):
            report = None
        exit_code = result.get("exit_code")
        if exit_code == 0 and report is not None and report.get("status") == "pass":
            return CharterOutcome(True, "charter check passed", report)

        failures: list[str] = []
        if report is not None:
            atoms = report.get("atoms")
            if isinstance(atoms, list):
                for atom in atoms:
                    if not isinstance(atom, dict) or atom.get("status") == "ok":
                        continue
                    name = str(atom.get("name") or "<unknown>")
                    status = str(atom.get("status") or "failed")
                    detail = atom.get("detail")
                    failures.append(
                        f"{name}: {status} ({detail})" if detail else f"{name}: {status}"
                    )
        if failures:
            summary = "; ".join(failures)
        else:
            output = str(result.get("stderr") or result.get("stdout") or "").strip()
            summary = f"charter check failed (exit code {exit_code})"
            if output:
                summary = f"{summary}: {output}"
        return CharterOutcome(False, summary, report)
